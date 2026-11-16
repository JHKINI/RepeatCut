import { useEffect, useState } from 'react'
import { api } from '../lib/api'

// 로그인해야 볼 수 있는 이미지.
// <img src="주소">는 로그인 토큰(헤더)을 보낼 수 없어서, api()로 이미지를 받아 온 뒤
// 브라우저 안에서만 쓰는 임시 주소(blob:)를 만들어 <img>에 넣는다.
//  path  API 경로 (예: mistakes/3/image)
export function AuthImage({ path, alt, style }) {
  const [src, setSrc] = useState('')
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    let objectUrl = ''
    setSrc('')
    setFailed(false)

    api(path)
      .then((response) => {
        if (!response.ok) throw new Error(`이미지 요청 실패 (HTTP ${response.status})`)
        return response.blob()
      })
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })

    // 화면에서 사라지거나 다른 이미지로 바뀌면 임시 주소를 지워서 메모리를 돌려준다
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  if (failed) return <div className="image-placeholder" role="img" aria-label={alt}>이미지를 불러오지 못했어요</div>
  if (!src) return <div className="image-placeholder" aria-hidden="true" />
  return <img src={src} alt={alt} style={style} />
}
