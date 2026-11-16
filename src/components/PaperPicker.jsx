import { useEffect, useState } from 'react'
import { api, getJson } from '../lib/api'
import { readError } from '../lib/errors'
import { paperDisplayTitle } from '../lib/paperTitle'

// 문제지 고르기 + 추가 / 수정 / 삭제.
//  papers          서버에서 받은 문제지 목록 (맨 위 = 가장 최근에 쓴 것)
//  value           선택된 문제지 id (문자열, 없으면 '')
//  onSelect(id)    선택이 바뀔 때
//  onPapersChange  목록이 바뀔 때(추가·수정·삭제 후) 새 목록을 부모에게 알려준다
const emptyForm = { exam: '', year: '', exam_type: '', round: '', title: '', total_questions: '' }

export function PaperPicker({ papers, options, value, onSelect, onPapersChange }) {
  const [mode, setMode] = useState(null) // null | 'new' | 'edit'
  const [form, setForm] = useState(emptyForm)
  const [message, setMessage] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [exams, setExams] = useState([]) // 내가 써 본 시험명 (입력창 자동완성용)

  // 추가/수정 상자를 열 때마다 시험명 목록을 새로 받아 온다
  useEffect(() => {
    if (!mode) return
    getJson('exams').then(setExams).catch(() => setExams([]))
  }, [mode])

  const selected = papers.find((paper) => String(paper.id) === String(value))
  const changeForm = (key, next) => setForm((current) => ({ ...current, [key]: next }))

  const closeBox = () => {
    setMode(null)
    setMessage('')
  }

  const openNew = () => {
    const lastPaper = papers[0] // 가장 최근에 쓴 문제지의 연도를 기본값으로
    setForm({
      exam: options.exam_default,
      year: String(lastPaper?.year || options.years[0] || ''),
      exam_type: options.exam_types[0] || '기출',
      round: options.rounds[0] || '상반기',
      title: '',
      total_questions: '',
    })
    setConfirmingDelete(false)
    setMessage('')
    setMode('new')
  }

  const openEdit = () => {
    if (!selected) return
    setForm({
      exam: selected.exam,
      // 예전 데이터는 연도가 비어 있을 수 있다. 그 경우 빈 칸으로 두고 직접 고르게 한다.
      year: selected.year ? String(selected.year) : '',
      exam_type: selected.exam_type,
      round: selected.round,
      title: selected.title || '',
      total_questions: selected.total_questions ? String(selected.total_questions) : '',
    })
    setConfirmingDelete(false)
    setMessage('')
    setMode('edit')
  }

  const save = async () => {
    setMessage('')
    if (!form.year) {
      setMessage('연도를 선택해 주세요.')
      return
    }
    const total = form.total_questions.trim()
    if (total && (!/^\d+$/.test(total) || Number(total) < 1 || Number(total) > options.max_questions)) {
      setMessage(`문항 수는 1~${options.max_questions} 사이의 숫자로 입력해 주세요.`)
      return
    }
    setBusy(true)
    try {
      const response = await api(mode === 'edit' ? `papers/${selected.id}` : 'papers', {
        method: mode === 'edit' ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exam: form.exam.trim(),
          year: Number(form.year),
          exam_type: form.exam_type,
          round: form.round,
          title: form.title.trim(),
          total_questions: total ? Number(total) : null,
        }),
      })
      if (!response.ok) throw new Error(await readError(response, mode === 'edit' ? '문제지 수정 실패' : '문제지 추가 실패'))
      const saved = await response.json()

      if (mode === 'edit') {
        onPapersChange(papers.map((paper) => (paper.id === saved.id ? saved : paper)))
      } else {
        // 이미 있던 문제지면 목록에 그대로 있으니 새로 넣지 않고, 맨 위로 올려서 선택한다.
        onPapersChange([saved, ...papers.filter((paper) => paper.id !== saved.id)])
      }
      onSelect(String(saved.id))
      closeBox()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '문제지를 저장하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  // 입력칸에서 Enter를 누르면 (전체 폼이 제출되지 않고) 문제지만 저장한다.
  const keyDown = (event) => {
    if (event.key === 'Enter' && event.target.tagName === 'INPUT') {
      event.preventDefault()
      save()
    }
  }

  const deletePaper = async () => {
    setMessage('')
    setBusy(true)
    try {
      const response = await api(`papers/${selected.id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error(await readError(response, '문제지 삭제 실패'))
      const rest = papers.filter((paper) => paper.id !== selected.id)
      onPapersChange(rest)
      onSelect(rest.length > 0 ? String(rest[0].id) : '')
      setConfirmingDelete(false)
    } catch (err) {
      setConfirmingDelete(false)
      setMessage(err instanceof Error ? err.message : '문제지를 삭제하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  // 오답이 연결된 문제지는 삭제할 수 없다. 먼저 이유를 알려주고 버튼은 막아 둔다.
  const hasMistakes = !!selected && selected.mistake_count > 0
  const autoTitle = paperDisplayTitle({ ...form, title: '' })

  return (
    <div className="field-group">
      <span className="field-label">문제지</span>
      <div className="paper-row">
        <select
          aria-label="문제지 선택"
          value={value}
          onChange={(event) => {
            onSelect(event.target.value)
            setConfirmingDelete(false)
            setMessage('')
          }}
        >
          <option value="">문제지를 선택하세요</option>
          {papers.map((paper) => (
            <option key={paper.id} value={paper.id}>
              {paper.display_title}{paper.mistake_count ? ` · 오답 ${paper.mistake_count}개` : ''}
            </option>
          ))}
        </select>
        <button type="button" className="button muted press" onClick={mode === 'new' ? closeBox : openNew}>
          {mode === 'new' ? '닫기' : '＋ 새 문제지'}
        </button>
      </div>

      {selected && mode === null && (
        <div className="paper-tools">
          <span className="field-hint">
            {selected.total_questions ? `총 ${selected.total_questions}문항 · ` : '문항 수 미입력 · '}
            등록된 오답 {selected.mistake_count}개
          </span>
          <button type="button" className="text-button" onClick={openEdit}>수정</button>
          {!confirmingDelete && (
            <button
              type="button"
              className="text-button danger"
              disabled={hasMistakes}
              title={hasMistakes ? '오답이 연결된 문제지는 삭제할 수 없어요' : undefined}
              onClick={() => setConfirmingDelete(true)}
            >
              삭제
            </button>
          )}
        </div>
      )}
      {selected && mode === null && hasMistakes && (
        <p className="field-hint">이 문제지에는 오답 {selected.mistake_count}개가 연결되어 있어서 삭제할 수 없어요. 오답을 먼저 삭제하거나 다른 문제지로 옮겨 주세요.</p>
      )}
      {confirmingDelete && selected && (
        <div className="confirm-row" role="alertdialog" aria-label="문제지 삭제 확인">
          <span>“{selected.display_title}” 문제지를 삭제할까요?</span>
          <button type="button" className="button danger-button press" disabled={busy} onClick={deletePaper}>삭제</button>
          <button type="button" className="button muted press" onClick={() => setConfirmingDelete(false)}>취소</button>
        </div>
      )}

      {mode && (
        <div className="new-paper-box" onKeyDown={keyDown}>
          <strong className="box-title">{mode === 'edit' ? '문제지 수정' : '새 문제지'}</strong>
          <div className="form-grid">
            <label>시험명
              <input list="exam-options" autoComplete="off" value={form.exam} onChange={(event) => changeForm('exam', event.target.value)} placeholder="예: 지역농협" />
              <datalist id="exam-options">
                {exams.map((exam) => <option key={exam.id} value={exam.name} />)}
              </datalist>
            </label>
            <label>연도
              <select value={form.year} onChange={(event) => changeForm('year', event.target.value)}>
                {!form.year && <option value="">연도를 선택하세요</option>}
                {options.years.map((year) => <option key={year} value={year}>{year}년</option>)}
              </select>
            </label>
            <label>시험 구분
              <select value={form.exam_type} onChange={(event) => changeForm('exam_type', event.target.value)}>
                {options.exam_types.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
            <label>회차
              <select value={form.round} onChange={(event) => changeForm('round', event.target.value)}>
                {options.rounds.map((round) => <option key={round} value={round}>{round}</option>)}
              </select>
            </label>
          </div>
          <label>문제지 이름 (선택)
            <input value={form.title} onChange={(event) => changeForm('title', event.target.value)} placeholder={autoTitle} />
          </label>
          <p className="field-hint">이름을 비워두면 “{autoTitle}”(으)로 저장돼요.</p>
          <label>문항 수 (선택)
            <input inputMode="numeric" value={form.total_questions} onChange={(event) => changeForm('total_questions', event.target.value)} placeholder="예: 60" />
          </label>
          <p className="field-hint">문항 수를 넣어 두면 통계에서 오답률(오답 수 ÷ 문항 수)을 계산해 줘요.</p>
          {mode === 'edit' && selected?.mistake_count > 0 && (
            <p className="field-hint">이 문제지에 기록된 오답 {selected.mistake_count}개도 바뀐 이름으로 보여요.</p>
          )}
          {message && <p className="inline-error" role="alert">{message}</p>}
          <div className="form-actions">
            <button type="button" className="button muted press" onClick={closeBox}>취소</button>
            <button type="button" className="button primary press" disabled={busy} onClick={save}>
              {mode === 'edit' ? '수정 저장' : '문제지 추가'}
            </button>
          </div>
        </div>
      )}

      {mode === null && message && <p className="inline-error" role="alert">{message}</p>}
    </div>
  )
}
