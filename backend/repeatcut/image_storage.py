"""이미지 파일 저장소.

DB에는 이미지 파일 '이름'(mistakes.image_path)만 저장하고, 실제 이미지는 여기서 관리한다.
저장소를 바꿔도 DB와 API는 그대로이다.

  LocalImageStorage  서버 폴더에 저장 (기본). 배포 때는 영속 디스크(볼륨)에 이 폴더를 둔다.
  S3ImageStorage     S3 호환 저장소(AWS S3, Cloudflare R2, MinIO 등)에 저장.

둘 다 같은 4개 메서드를 가진다: save / delete / exists / serve
"""
import base64
import os
import re
from dataclasses import dataclass


@dataclass
class ServedImage:
    """이미지를 어떻게 내려줄지.
    kind == "file"     -> location은 서버 안의 파일 경로 (파일 그대로 응답)
    kind == "redirect" -> location은 이동할 URL (브라우저가 그 주소에서 이미지를 받음)"""
    kind: str
    location: str


class ImageError(ValueError):
    """업로드된 이미지에 문제가 있을 때. status는 API가 돌려줄 HTTP 상태 코드."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# 파일 맨 앞 바이트로 진짜 이미지인지 확인한다. (data:image/png 라고 적혀 있어도 내용이 다르면 거부)
def sniff_image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def decode_image_data(image_data, max_bytes):
    """'data:image/png;base64,....' 문자열을 (이미지 바이트, 확장자, content_type)으로 바꾼다."""
    match = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", image_data.strip(), re.DOTALL)
    if not match:
        raise ImageError(400, "이미지 형식을 확인해 주세요.")
    try:
        data = base64.b64decode("".join(match.group(2).split()), validate=True)
    except Exception:
        raise ImageError(400, "이미지 데이터를 확인해 주세요.")
    if not data:
        raise ImageError(400, "이미지 데이터를 확인해 주세요.")
    if len(data) > max_bytes:
        raise ImageError(413, f"이미지는 {max_bytes / 1024 / 1024:g}MB 이하만 올릴 수 있어요.")
    kind = sniff_image_type(data)
    if kind is None:
        raise ImageError(400, "이미지 파일이 아니에요. PNG, JPG, WEBP만 올릴 수 있어요.")
    return data, kind[0], kind[1]


def check_filename(filename):
    """파일 이름에 경로(../ 등)가 섞여 들어오지 못하게 막는다."""
    if not filename or filename != os.path.basename(filename) or filename.startswith("."):
        raise ValueError(f"올바르지 않은 파일 이름이에요: {filename!r}")
    return filename


class LocalImageStorage:
    name = "local"

    def __init__(self, directory, legacy_directories=()):
        self.directory = directory
        # 예전에 저장된 이미지가 있는 폴더들. 읽기·삭제만 하고 새 이미지는 저장하지 않는다.
        self.legacy_directories = tuple(legacy_directories)

    def _all_directories(self):
        return (self.directory, *self.legacy_directories)

    def _find(self, filename):
        check_filename(filename)
        for directory in self._all_directories():
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                return path
        return None

    def save(self, filename, data, content_type=None):
        check_filename(filename)
        os.makedirs(self.directory, exist_ok=True)
        path = os.path.join(self.directory, filename)
        temp_path = path + ".tmp"
        with open(temp_path, "wb") as file:
            file.write(data)
        os.replace(temp_path, path)  # 다 쓴 뒤에 이름을 바꿔서, 쓰다 만 파일이 남지 않게 한다

    def exists(self, filename):
        return self._find(filename) is not None

    def serve(self, filename):
        path = self._find(filename)
        return ServedImage("file", path) if path else None

    def delete(self, filename):
        check_filename(filename)
        for directory in self._all_directories():
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                os.remove(path)


class S3ImageStorage:
    name = "s3"

    def __init__(self, client, bucket, prefix="", public_base_url="", presign_seconds=3600, local_fallback=None):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.public_base_url = public_base_url
        self.presign_seconds = presign_seconds
        # S3로 옮기기 전에 로컬 폴더에 저장돼 있던 이미지도 계속 보여주기 위한 읽기용 저장소
        self.local_fallback = local_fallback

    def _key(self, filename):
        return f"{self.prefix}{check_filename(filename)}"

    def save(self, filename, data, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=self._key(filename), Body=data, **extra)

    def exists(self, filename):
        if self.local_fallback and self.local_fallback.exists(filename):
            return True
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(filename))
            return True
        except Exception as error:  # botocore를 import하지 않으려고 에러 코드로 구분한다
            code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def serve(self, filename):
        if self.local_fallback and self.local_fallback.exists(filename):
            return self.local_fallback.serve(filename)
        key = self._key(filename)
        if self.public_base_url:  # 버킷이 공개(CDN)라면 주소만 조합하면 된다
            return ServedImage("redirect", f"{self.public_base_url}/{key}")
        url = self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.presign_seconds
        )
        return ServedImage("redirect", url)

    def delete(self, filename):
        self.client.delete_object(Bucket=self.bucket, Key=self._key(filename))
        if self.local_fallback:
            self.local_fallback.delete(filename)


def build_image_storage(config, client=None):
    """Settings에 맞는 저장소를 만든다. (client는 테스트에서 가짜 S3 클라이언트를 넣을 때만 사용)"""
    local = LocalImageStorage(config.upload_dir, config.legacy_upload_dirs)
    if config.storage_backend == "local":
        return local

    if client is None:
        try:
            import boto3  # S3를 쓸 때만 필요해서 여기서 불러온다
        except ImportError:
            raise RuntimeError("S3 저장소를 쓰려면 boto3가 필요해요: pip install boto3")
        options = {}
        if config.s3_endpoint_url:
            options["endpoint_url"] = config.s3_endpoint_url
        if config.s3_region:
            options["region_name"] = config.s3_region
        client = boto3.client("s3", **options)

    return S3ImageStorage(
        client,
        config.s3_bucket,
        prefix=config.s3_prefix,
        public_base_url=config.s3_public_base_url,
        presign_seconds=config.s3_presign_seconds,
        local_fallback=local,
    )
