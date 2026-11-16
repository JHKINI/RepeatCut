import { useEffect, useRef, useState } from 'react'
import { api, getJson } from '../lib/api'
import { readError } from '../lib/errors'
import { AnswerChips, SAME_ANSWER_TEXT, sameAnswerMessage } from './AnswerChips'
import { PaperPicker } from './PaperPicker'

const initialDraft = { paperId: '', problemNo: '', page: '', keyword: '', reasonType: '', memo: '', myAnswer: '', correctAnswer: '' }
// 서버(/api/options)에서 받아오기 전까지 쓰는 빈 값
const emptyOptions = { exam_default: '지역농협', exam_types: [], rounds: [], reason_types: [], answer_choices: [], years: [], max_questions: 500 }

export function RegisterMistake({ onSaved, onCancel }) {
  const [draft, setDraft] = useState(initialDraft)
  const [source, setSource] = useState('')
  const [sourceFile, setSourceFile] = useState(null)
  const [imageRatio, setImageRatio] = useState('5 / 4')
  const [crop, setCrop] = useState('')
  const [selection, setSelection] = useState(null)
  const [dragStart, setDragStart] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const imageRef = useRef(null)
  const canvasRef = useRef(null)

  // 선택 목록: 시험구분/회차/오답이유/연도, 저장해 둔 문제지, 지금까지 쓴 키워드
  const [options, setOptions] = useState(emptyOptions)
  const [papers, setPapers] = useState([])
  const [keywords, setKeywords] = useState([])

  // ── 이미 등록한 문제인지 확인 ──
  // 문제지와 문제 번호를 정하면 서버에 물어본다. 이미 있으면 existing에 그 오답이 들어오고,
  // 새로 등록하는 대신 "이번에 고른 답"만 기록하는 화면으로 바뀐다.
  const [existing, setExisting] = useState(null)
  const [againAnswer, setAgainAnswer] = useState('')
  const [againReason, setAgainReason] = useState('')

  useEffect(() => {
    Promise.all([getJson('options'), getJson('papers'), getJson('keywords')])
      .then(([optionData, paperList, keywordList]) => {
        setOptions(optionData)
        setPapers(paperList)
        setKeywords(keywordList)
        // 목록 맨 위 = 가장 최근에 쓴 문제지. 기본으로 선택해 둔다.
        if (paperList.length > 0) {
          setDraft((current) => ({ ...current, paperId: String(paperList[0].id) }))
        }
      })
      .catch(() => setError('선택 목록을 불러오지 못했습니다. 서버가 켜져 있는지 확인해 주세요.'))
  }, [])

  const paperIdForLookup = draft.paperId
  const problemNoForLookup = draft.problemNo.trim()
  useEffect(() => {
    setExisting(null)
    setAgainAnswer('')
    setAgainReason('')
    if (!paperIdForLookup || !problemNoForLookup) return
    let cancelled = false
    // 글자를 칠 때마다 묻지 않도록, 입력이 0.3초 멈추면 한 번만 확인한다
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ paper_id: paperIdForLookup, problem_no: problemNoForLookup })
      getJson(`mistakes/lookup?${params.toString()}`)
        .then((data) => { if (!cancelled) setExisting(data.mistake) })
        .catch(() => { if (!cancelled) setExisting(null) }) // 확인에 실패해도 등록은 막지 않는다 (서버가 저장할 때 다시 확인한다)
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [paperIdForLookup, problemNoForLookup])

  // 이미 등록한 문제: 오답을 새로 만들지 않고 '또 틀림' 기록만 하나 더한다
  const saveWrongAgain = async () => {
    setError('')
    if (!againReason) {
      setError('이번에 틀린 이유를 선택해 주세요.')
      return
    }
    setSaving(true)
    try {
      const response = await api(`mistakes/${existing.id}/attempts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_correct: false, my_answer: againAnswer, reason_type: againReason }),
      })
      if (!response.ok) throw new Error(await readError(response, '기록 실패'))
      onSaved?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : '기록하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const selectImage = (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('이미지 파일만 선택할 수 있습니다.')
      return
    }
    setSourceFile(file)
    const reader = new FileReader()
    reader.onload = () => {
      setSource(String(reader.result))
      setImageRatio('5 / 4')
      setCrop('')
      setSelection(null)
      setDragStart(null)
      setError('')
    }
    reader.readAsDataURL(file)
  }

  const pointFromEvent = (event) => {
    const image = imageRef.current
    if (!image) return null
    const bounds = image.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return null
    return {
      x: Math.max(0, Math.min(100, ((event.clientX - bounds.left) / bounds.width) * 100)),
      y: Math.max(0, Math.min(100, ((event.clientY - bounds.top) / bounds.height) * 100)),
    }
  }

  const startSelection = (event) => {
    const point = pointFromEvent(event)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDragStart(point)
    setSelection({ x: point.x, y: point.y, width: 0, height: 0 })
    setCrop('')
  }

  const updateSelection = (event) => {
    if (!dragStart) return
    const point = pointFromEvent(event)
    if (!point) return
    setSelection({
      x: Math.min(dragStart.x, point.x),
      y: Math.min(dragStart.y, point.y),
      width: Math.abs(point.x - dragStart.x),
      height: Math.abs(point.y - dragStart.y),
    })
  }

  const finishSelection = (event) => {
    if (dragStart) {
      updateSelection(event)
      setDragStart(null)
    }
  }

  const makeCrop = () => {
    const image = imageRef.current
    const canvas = canvasRef.current
    if (!image || !canvas || !selection || selection.width < 2 || selection.height < 2) {
      setError('이미지에서 저장할 영역을 드래그해 선택해 주세요.')
      return
    }

    const sourceX = Math.round((selection.x / 100) * image.naturalWidth)
    const sourceY = Math.round((selection.y / 100) * image.naturalHeight)
    const sourceWidth = Math.max(1, Math.round((selection.width / 100) * image.naturalWidth))
    const sourceHeight = Math.max(1, Math.round((selection.height / 100) * image.naturalHeight))
    const scale = Math.max(sourceWidth, sourceHeight) > 1200 ? 1200 / Math.max(sourceWidth, sourceHeight) : 1

    canvas.width = Math.max(1, Math.round(sourceWidth * scale))
    canvas.height = Math.max(1, Math.round(sourceHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, canvas.width, canvas.height)
    setCrop(canvas.toDataURL('image/jpeg', 0.9))
    setError('')
  }

  const submit = async (event) => {
    event.preventDefault()
    setError('')

    if (!draft.paperId) {
      setError('문제지를 선택하거나 새로 추가해 주세요.')
      return
    }
    if (!draft.problemNo.trim() || !draft.keyword.trim()) {
      setError('문제 번호와 핵심 키워드를 입력해 주세요.')
      return
    }
    if (!draft.reasonType) {
      setError('오답 이유를 선택해 주세요.')
      return
    }
    if (sameAnswer) {
      setError(sameAnswer)
      return
    }
    if (!sourceFile) {
      setError('원본 문제 이미지를 먼저 선택해 주세요.')
      return
    }
    if (!crop) {
      setError('문제 이미지에서 저장할 영역을 먼저 잘라 주세요.')
      return
    }

    setSaving(true)
    try {
      const response = await api('mistakes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper_id: Number(draft.paperId),
          problem_no: draft.problemNo.trim(),
          page: draft.page ? Number(draft.page) : 0, // 비우면 0 = 입력 안 함
          keyword: draft.keyword.trim(),
          reason_type: draft.reasonType,
          memo: draft.memo.trim(),
          my_answer: draft.myAnswer,
          correct_answer: draft.correctAnswer,
          image_data: crop,
        }),
      })

      if (!response.ok) throw new Error(await readError(response, '등록 실패'))
      setDraft(initialDraft)
      setSource('')
      setSourceFile(null)
      setCrop('')
      setSelection(null)
      onSaved?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : '등록하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const field = (key, value) => setDraft((current) => ({ ...current, [key]: value }))
  const selectionStyle = selection
    ? { left: `${selection.x}%`, top: `${selection.y}%`, width: `${selection.width}%`, height: `${selection.height}%` }
    : undefined

  const sameAnswer = sameAnswerMessage(draft.myAnswer, draft.correctAnswer)
  // '답이 같아요' 오류는 답을 고쳐서 같지 않게 되면 저절로 사라진다
  const visibleError = error === SAME_ANSWER_TEXT && !sameAnswer ? '' : error
  // 입력한 키워드가 기존 목록에 없으면 새 키워드로 추가된다는 안내를 띄운다
  const typedKeyword = draft.keyword.trim().split(/\s+/).filter(Boolean).join(' ').toLowerCase()
  const keywordIsNew = typedKeyword !== '' && !keywords.some((item) => item.name.toLowerCase() === typedKeyword)

  return (
    <section className="register-layout">
      <div className="register-heading">
        <button className="back-button" onClick={onCancel}>← 목록으로</button>
        <p className="eyebrow">오답 기록</p>
        <h2>문제의 핵심만 잘라 저장하세요</h2>
        <p>이미지를 선택하고 필요한 부분을 드래그해 저장하세요. 문제지와 키워드는 한 번 입력해 두면 다음부터 목록에서 고를 수 있어요.</p>
      </div>

      <form onSubmit={submit} className="register-grid">
        <div className="crop-panel">
          <h3>1. 문제 이미지 선택 및 영역 자르기</h3>
          <label className="upload-zone">
            <input type="file" accept="image/*" onChange={selectImage} />
            <span>＋</span>
            <strong>문제 이미지 선택</strong>
            <small>이미지 위에서 필요한 부분을 드래그해 선택할 수 있습니다.</small>
          </label>

          {source && (
            <>
              <div
                className="crop-stage selectable"
                style={{ aspectRatio: imageRatio }}
                onPointerDown={startSelection}
                onPointerMove={updateSelection}
                onPointerUp={finishSelection}
                onPointerCancel={finishSelection}
              >
                <img
                  ref={imageRef}
                  src={source}
                  alt="선택한 문제지 원본"
                  draggable="false"
                  onLoad={(event) => {
                    const img = event.currentTarget
                    if (img.naturalWidth && img.naturalHeight) {
                      setImageRatio(`${img.naturalWidth} / ${img.naturalHeight}`)
                    }
                  }}
                />
                {selection && <div className="crop-guide selected" style={selectionStyle} aria-label="잘라낼 영역" />}
              </div>
              <p className="crop-help">원하는 문제 영역을 드래그한 다음 아래 버튼을 눌러 미리 보세요.</p>
              <button type="button" className="button accent press" onClick={makeCrop}>선택 영역 자르기</button>
            </>
          )}

          {crop && (
            <div className="preview">
              <span>저장될 문제 이미지<br /><small>잘라낸 영역이 자동 저장됩니다.</small></span>
              <img src={crop} alt="잘라낸 문제 영역 미리보기" />
            </div>
          )}
          <canvas ref={canvasRef} className="visually-hidden" />
        </div>

        <div className="form-panel">
          <h3>2. 오답 정보 기록</h3>

          {/* 문제지: 목록에서 고르기 (없으면 새로 추가, 고른 문제지는 수정·삭제 가능) */}
          <PaperPicker
            papers={papers}
            options={options}
            value={draft.paperId}
            onSelect={(id) => field('paperId', id)}
            onPapersChange={setPapers}
          />

          <div className="form-grid" style={{ marginTop: 'var(--space-3)' }}>
            <label>문제 번호
              <input value={draft.problemNo} onChange={(event) => field('problemNo', event.target.value)} placeholder="예: 17" />
            </label>
            <label>페이지 (선택)
              <input type="number" min="1" value={draft.page} onChange={(event) => field('page', event.target.value)} placeholder="예: 83" />
            </label>
          </div>

          {existing ? (
            <div className="existing-box" role="status">
              <strong>이미 등록한 문제예요</strong>
              <p className="field-hint">
                {existing.paper_title} · {existing.problem_no}번 · #{existing.keyword} · 처음 등록 {(existing.created_at || '').slice(0, 10)}
                {existing.correct_answer ? ` · 정답 ${existing.correct_answer}` : ''}
              </p>
              <p>지금까지 <strong className="tabular">{existing.wrong_total}번</strong> 틀렸어요. 이미지와 키워드는 그대로 두고, 이번에 또 틀린 것만 기록할게요.</p>
              <div className="field-group">
                <span className="field-label" id="again-reason-label">이번에 틀린 이유 <span className="field-hint">(처음 등록할 때: {existing.reason_type})</span></span>
                <div className="choice-row" role="group" aria-labelledby="again-reason-label">
                  {options.reason_types.map((reason) => (
                    <button type="button" key={reason} className="choice-chip" aria-pressed={againReason === reason} onClick={() => setAgainReason(reason)}>
                      {reason}
                    </button>
                  ))}
                </div>
              </div>
              <AnswerChips label="이번에 고른 답 (선택)" name="again" value={againAnswer} choices={options.answer_choices} onChange={setAgainAnswer} />
              {visibleError && <p className="inline-error">{visibleError}</p>}
              <div className="form-actions">
                <button type="button" className="button muted press" onClick={onCancel}>취소</button>
                <button type="button" className="button primary press" disabled={saving} onClick={saveWrongAgain}>
                  {saving ? '기록 중…' : '또 틀린 것으로 기록'}
                </button>
              </div>
            </div>
          ) : (
          <>
          {/* 키워드: 입력하면 기존 키워드가 자동완성으로 나오고, 자주 쓴 키워드는 눌러서 바로 선택 */}
          <div className="field-group">
            <label htmlFor="keyword-input" className="field-label">핵심 키워드</label>
            <input
              id="keyword-input"
              list="keyword-options"
              autoComplete="off"
              value={draft.keyword}
              onChange={(event) => field('keyword', event.target.value)}
              placeholder="예: 농도, 일률, 증감률"
            />
            <datalist id="keyword-options">
              {keywords.map((item) => <option key={item.id} value={item.name} />)}
            </datalist>
            {keywords.length > 0 && (
              <div className="choice-row">
                {keywords.slice(0, 8).map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className="choice-chip"
                    aria-pressed={draft.keyword.trim() === item.name}
                    onClick={() => field('keyword', item.name)}
                  >
                    #{item.name}
                  </button>
                ))}
              </div>
            )}
            {keywordIsNew && <p className="field-hint">목록에 없는 키워드예요. 저장하면 새 키워드로 추가돼요.</p>}
          </div>

          {/* 오답 이유: 목록에서 고르기 */}
          <div className="field-group">
            <span className="field-label" id="reason-label">오답 이유</span>
            <div className="choice-row" role="group" aria-labelledby="reason-label">
              {options.reason_types.map((reason) => (
                <button
                  type="button"
                  key={reason}
                  className="choice-chip"
                  aria-pressed={draft.reasonType === reason}
                  onClick={() => field('reasonType', reason)}
                >
                  {reason}
                </button>
              ))}
            </div>
          </div>

          {/* 내가 고른 답 / 정답 (선택): 통계에서 어떤 번호로 자주 틀리는지 볼 수 있어요 */}
          <AnswerChips label="내가 고른 답 (선택)" name="my" value={draft.myAnswer} choices={options.answer_choices} onChange={(next) => field('myAnswer', next)} />
          <AnswerChips label="정답 (선택)" name="correct" value={draft.correctAnswer} choices={options.answer_choices} onChange={(next) => field('correctAnswer', next)} />
          {sameAnswer && <p className="field-hint warn-hint">{sameAnswer}</p>}

          <label className="wide-label">메모 (선택)
            <textarea value={draft.memo} onChange={(event) => field('memo', event.target.value)} placeholder="어떤 판단이나 개념에서 실수했는지 적어 보세요." rows={4} />
          </label>
          {visibleError && <p className="inline-error">{visibleError}</p>}
          <div className="form-actions">
            <button type="button" className="button muted press" onClick={onCancel}>취소</button>
            <button className="button primary press" disabled={saving}>
              {saving ? '저장 중…' : '오답 기록 저장'}
            </button>
          </div>
          </>
          )}
        </div>
      </form>
    </section>
  )
}
