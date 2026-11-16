// 문제지 이름을 비워뒀을 때 자동으로 만드는 이름.
// backend/main.py의 paper_display_title()과 같은 규칙이다. (바꾸려면 두 곳을 같이 고치기)
//   예) 2025 지역농협 상반기 / 2025 지역농협 1회차 모의고사
export function paperDisplayTitle({ exam, year, exam_type, round, title }) {
  const custom = (title || '').trim().split(/\s+/).filter(Boolean).join(' ')
  if (custom) return custom

  const parts = []
  if (year) parts.push(String(year))
  parts.push((exam || '').trim() || '지역농협')
  if (round && round !== '기타') parts.push(round)
  if (exam_type && exam_type !== '기출') parts.push(exam_type)
  return parts.join(' ')
}
