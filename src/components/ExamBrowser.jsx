import { useEffect, useMemo, useState } from 'react'
import { api, getJson } from '../lib/api'
import { readError } from '../lib/errors'
import { MistakeLibrary } from './MistakeLibrary'

// 오답 기록의 첫 화면.  시험 이름 → 시험 유형 → 연도별 회차 목록(검색 가능) → 오답 목록
//  - 따로 시험 API를 만들지 않고 /api/papers 한 번으로 세 단계를 모두 만든다. (문제지마다 시험명·유형·연도·회차가 있다)
//  - 고른 단계는 위쪽 경로(시험 > 유형)를 눌러 되돌아갈 수 있다.
export function ExamBrowser({ onRegister }) {
  const [papers, setPapers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exam, setExam] = useState(null)         // 고른 시험명 (문자열)
  const [examType, setExamType] = useState(null) // 고른 시험 유형 (문자열)
  const [paper, setPaper] = useState(null)       // 고른 문제지 (객체)
  const [filter, setFilter] = useState('')       // 회차 목록 검색어

  const [notice, setNotice] = useState('')

  const loadPapers = () => getJson('papers')
    .then((rows) => setPapers(Array.isArray(rows) ? rows : []))
    .catch((err) => setError(err instanceof Error ? err.message : '문제지를 불러오지 못했습니다.'))
    .finally(() => setLoading(false))

  useEffect(() => { loadPapers() }, [])

  // 시험 이름 바꾸기 (대소문자 고치기 포함). 내 문제지에만 적용된다.
  const renameExam = async (row) => {
    const next = window.prompt('새 시험 이름', row.name)
    if (next === null) return
    const name = next.trim()
    if (!name || name === row.name) return
    setNotice('')
    try {
      const response = await api(`exams/${row.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!response.ok) throw new Error(await readError(response, '이름을 바꾸지 못했어요.'))
      await loadPapers()
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '이름을 바꾸지 못했어요.')
    }
  }

  // 시험 지우기. 오답이 있으면 개수를 보여 주고 한 번 더 확인한다.
  const deleteExam = async (row) => {
    const message = row.mistakes
      ? `"${row.name}"의 문제지 ${row.papers}개와 오답 ${row.mistakes}개가 모두 삭제돼요. 복구할 수 없어요. 지울까요?`
      : `"${row.name}"의 문제지 ${row.papers}개를 삭제할까요?`
    if (!window.confirm(message)) return
    setNotice('')
    try {
      const response = await api(`exams/${row.id}?with_mistakes=${row.mistakes ? 'true' : 'false'}`, { method: 'DELETE' })
      if (!response.ok) throw new Error(await readError(response, '삭제하지 못했어요.'))
      await loadPapers()
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '삭제하지 못했어요.')
    }
  }

  // 1단계: 시험명별 문제지 수·오답 수
  const exams = useMemo(() => {
    const byExam = new Map()
    papers.forEach((p) => {
      const row = byExam.get(p.exam) || { id: p.exam_id, name: p.exam, papers: 0, mistakes: 0 }
      row.papers += 1
      row.mistakes += p.mistake_count
      byExam.set(p.exam, row)
    })
    return [...byExam.values()]
  }, [papers])

  // 2단계: 고른 시험 안의 유형별 문제지 수·오답 수
  const types = useMemo(() => {
    const byType = new Map()
    papers.filter((p) => p.exam === exam).forEach((p) => {
      const row = byType.get(p.exam_type) || { name: p.exam_type, papers: 0, mistakes: 0 }
      row.papers += 1
      row.mistakes += p.mistake_count
      byType.set(p.exam_type, row)
    })
    return [...byType.values()]
  }, [papers, exam])

  // 3단계: 고른 시험·유형의 문제지를 검색어로 거른 뒤 연도별로 묶는다. (연도는 최근 것이 위, 연도 없음은 맨 아래)
  const yearGroups = useMemo(() => {
    const words = filter.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const rows = papers
      .filter((p) => p.exam === exam && p.exam_type === examType)
      .filter((p) => {
        const text = `${p.year || ''} ${p.round} ${p.title} ${p.display_title}`.toLowerCase()
        return words.every((word) => text.includes(word))
      })
    const byYear = new Map()
    rows.forEach((p) => {
      const key = p.year || 0
      byYear.set(key, [...(byYear.get(key) || []), p])
    })
    return [...byYear.entries()]
      .sort(([a], [b]) => (a === 0) - (b === 0) || b - a)
      .map(([year, list]) => ({ year, list: list.sort((a, b) => String(a.round).localeCompare(String(b.round), 'ko', { numeric: true })) }))
  }, [papers, exam, examType, filter])

  const goExams = () => { setExam(null); setExamType(null); setPaper(null); setFilter('') }
  const goTypes = () => { setExamType(null); setPaper(null); setFilter('') }

  // 4단계: 고른 문제지의 오답 목록
  if (paper) {
    return <MistakeLibrary onRegister={onRegister} paper={paper} onBack={() => setPaper(null)} />
  }

  // 전체 오답을 시험 구분 없이 보는 화면도 남겨 둔다 (예전 화면 그대로)
  if (exam === '__all__') {
    return <MistakeLibrary onRegister={onRegister} onBack={goExams} />
  }

  if (loading) return <div className="state-card">시험 목록을 불러오는 중입니다.</div>
  if (error) return <div className="state-card"><p>{error}</p></div>

  if (!papers.length) {
    return <div className="state-card">
      <h2>아직 등록한 문제지가 없어요</h2>
      <p>오답을 등록하면 시험별로 모아서 보여드려요.</p>
      <button className="button primary press" onClick={onRegister}>첫 오답 등록하기</button>
    </div>
  }

  return <section className="library exam-browser">
    <div className="library-top">
      <div>
        <p className="eyebrow">오답 아카이브</p>
        <h2>{!exam ? '시험을 고르세요' : !examType ? '시험 유형을 고르세요' : '회차를 고르세요'}</h2>
        {exam && <nav className="crumbs" aria-label="선택 경로">
          <button className="text-button" onClick={goExams}>전체 시험</button>
          <span>›</span>
          {examType
            ? <button className="text-button" onClick={goTypes}>{exam}</button>
            : <strong>{exam}</strong>}
          {examType && <><span>›</span><strong>{examType}</strong></>}
        </nav>}
      </div>
      <button className="button primary press" onClick={onRegister}>＋ 오답 등록</button>
    </div>

    {!exam && <>
      <div className="pick-grid">
        {exams.map((row) => (
          <div key={row.name} className="pick-item">
            <button className="pick-card glass press" onClick={() => setExam(row.name)}>
              <strong>{row.name}</strong>
              <span>문제지 {row.papers}개 · 오답 {row.mistakes}개</span>
            </button>
            <div className="pick-tools">
              <button type="button" className="text-button" onClick={() => renameExam(row)}>이름 바꾸기</button>
              <button type="button" className="text-button danger" onClick={() => deleteExam(row)}>삭제</button>
            </div>
          </div>
        ))}
      </div>
      {notice && <p role="alert" className="pick-notice">{notice}</p>}
      <p className="pick-all"><button className="text-button" onClick={() => setExam('__all__')}>시험 구분 없이 전체 오답 보기</button></p>
    </>}

    {exam && !examType && (
      <div className="pick-grid">
        {types.map((row) => (
          <button key={row.name} className="pick-card glass press" onClick={() => setExamType(row.name)}>
            <strong>{row.name}</strong>
            <span>문제지 {row.papers}개 · 오답 {row.mistakes}개</span>
          </button>
        ))}
      </div>
    )}

    {exam && examType && <>
      <div className="search-box">
        <label className="visually-hidden" htmlFor="paper-filter">회차 검색</label>
        <input id="paper-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="연도, 회차, 이름으로 검색 (예: 2025 상반기)" />
      </div>
      {yearGroups.length === 0 && <div className="state-card"><p>검색 결과가 없어요.</p></div>}
      {yearGroups.map(({ year, list }) => (
        <section key={year} className="year-group" aria-label={year ? `${year}년` : '연도 없음'}>
          <h3>{year ? `${year}년` : '연도 없음'}</h3>
          <div className="pick-grid">
            {list.map((p) => (
              <button key={p.id} className="pick-card glass press" onClick={() => setPaper(p)}>
                <strong>{p.round && p.round !== '기타' ? p.round : p.display_title}</strong>
                <span>{p.title || p.display_title}</span>
                <span>오답 {p.mistake_count}개</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </>}
  </section>
}
