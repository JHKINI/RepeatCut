import { useEffect, useMemo, useRef, useState } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, getJson } from '../lib/api'
import { readError } from '../lib/errors'
import { AnswerChips, sameAnswerMessage } from './AnswerChips'
import { AuthImage } from './AuthImage'

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
const dateLabel = (value) => (value || '').replaceAll('-', '.')

// 추이 그래프에 한 번에 보여줄 날짜 개수, 끝에 마우스를 대고 있을 때 한 칸씩 넘어가는 간격(ms)
const TREND_WINDOW = 7
const TREND_SCROLL_MS = 350

const emptyEditForm = { paper_id: '', problem_no: '', page: '', keyword: '', reason_type: '', memo: '', my_answer: '', correct_answer: '' }
const emptyEditOptions = { papers: [], keywords: [], reasonTypes: [], answerChoices: [] }

// '내 답 3 → 정답 4' 처럼 한 줄로. 둘 다 비어 있으면 빈 문자열(= 화면에 안 보여줌)
const answerSummary = (item) => {
  const mine = item.my_answer ? `내 답 ${item.my_answer}` : ''
  const correct = item.correct_answer ? `정답 ${item.correct_answer}` : ''
  return [mine, correct].filter(Boolean).join(' → ')
}

// 다시 푼 기록 요약. 한 번도 안 풀었으면 빈 문자열
//  - 최근에 맞혔으면 "다시 맞힘", 아니면 "3번 틀림"(처음 등록 1번 + 또 틀린 횟수)
const retrySummary = (item) => {
  if (!item.attempt_count) return ''
  return item.last_is_correct ? `다시 맞힘 · 틀린 횟수 ${item.wrong_total}번` : `${item.wrong_total}번 틀림`
}


// paper: 시험 → 유형 → 회차에서 고른 문제지. 있으면 그 문제지의 오답만 보여준다. onBack: 회차 목록으로 돌아가기
export function MistakeLibrary({ onRegister, paper = null, onBack = null }) {
  const [items, setItems] = useState([])
  const [trend, setTrend] = useState([])
  const [keyword, setKeyword] = useState('')
  const [query, setQuery] = useState('')
  const [order, setOrder] = useState('newest')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedItem, setSelectedItem] = useState(null)
  const [isEditing, setIsEditing] = useState(false)
  const [newImage, setNewImage] = useState('') // 수정 중 새로 고른 문제 이미지(data URL). 비어 있으면 기존 이미지를 그대로 쓴다
  const [imageVersion, setImageVersion] = useState(0) // 이미지를 바꾼 뒤 <AuthImage>를 다시 불러오게 하는 번호
  const [editForm, setEditForm] = useState(emptyEditForm)
  const [editOptions, setEditOptions] = useState(emptyEditOptions) // 수정할 때 고를 수 있는 문제지/키워드/오답이유 목록
  const [actionError, setActionError] = useState('')
  const [attempts, setAttempts] = useState([]) // 지금 보고 있는 오답의 다시 푼 기록 (최근 것이 맨 위)
  const [attemptBusy, setAttemptBusy] = useState(false)

  const load = async (value = query, nextOrder = order) => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (value) params.set('keyword', value)
      params.set('order', nextOrder)
      if (paper) params.set('paper_id', paper.id)

      const listResponse = await api(`mistakes?${params.toString()}`)
      if (!listResponse.ok) {
        throw new Error(`오답 목록 조회 실패 (HTTP ${listResponse.status})`)
      }

      const rows = await listResponse.json()
      const safeRows = Array.isArray(rows) ? rows : []
      setItems(safeRows)

      // 백엔드에 추세 API가 있으므로 해당 데이터를 우선 사용하고,
      // 실패하면 현재 목록의 날짜로 추세를 계산한다.
      try {
        if (paper) throw new Error('문제지별 보기는 현재 목록으로 계산') // 전체 추세 API는 문제지 구분이 없다
        const trendResponse = await api('mistakes/trend')
        if (trendResponse.ok) {
          const trendRows = await trendResponse.json()
          setTrend(Array.isArray(trendRows) ? trendRows : [])
        } else {
          throw new Error('추세 API 오류')
        }
      } catch {
        const byDate = {}
        safeRows.forEach((item) => {
          const date = (item.created_at || '').slice(0, 10)
          if (date) byDate[date] = (byDate[date] || 0) + 1
        })
        setTrend(
          Object.entries(byDate)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([date, count]) => ({ date, count }))
        )
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '오답 목록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load('', 'newest')
  }, [])

  // ── 추이 그래프 넘기기 ──
  // trendEnd: 지금 보이는 구간의 끝 위치(이 번호 직전까지 보임). 처음엔 가장 최근 날짜까지.
  const [trendEnd, setTrendEnd] = useState(0)
  const scrollTimer = useRef(null)
  const scrollDirection = useRef(0) // -1: 이전(왼쪽), +1: 최근(오른쪽), 0: 멈춤

  // 추이 데이터가 새로 오면 가장 최근 구간으로 돌아간다
  useEffect(() => {
    setTrendEnd(trend.length)
  }, [trend])

  const trendStart = Math.max(0, trendEnd - TREND_WINDOW)
  const visibleTrend = trend.slice(trendStart, trendEnd)
  const canGoEarlier = trendStart > 0
  const canGoLater = trendEnd < trend.length

  // 한 칸 이동. 처음 구간보다 앞이나 마지막 날짜보다 뒤로는 못 간다.
  const stepTrend = (direction) => {
    setTrendEnd((end) => {
      const smallestEnd = Math.min(TREND_WINDOW, trend.length)
      return Math.min(trend.length, Math.max(smallestEnd, end + direction))
    })
  }

  const stopTrendScroll = () => {
    clearInterval(scrollTimer.current)
    scrollTimer.current = null
    scrollDirection.current = 0
  }

  // 마우스를 끝에 대는 순간 한 칸 넘기고, 대고 있는 동안 계속 넘긴다
  const startTrendScroll = (direction) => {
    stopTrendScroll()
    scrollDirection.current = direction
    stepTrend(direction)
    scrollTimer.current = setInterval(() => stepTrend(direction), TREND_SCROLL_MS)
  }

  // 맨 앞/맨 뒤에 닿으면 자동 넘기기를 멈춘다
  useEffect(() => {
    if (scrollDirection.current < 0 && !canGoEarlier) stopTrendScroll()
    if (scrollDirection.current > 0 && !canGoLater) stopTrendScroll()
  }, [canGoEarlier, canGoLater])

  // 화면을 떠날 때 타이머 정리
  useEffect(() => stopTrendScroll, [])

  const countLabel = useMemo(
    () => query ? `"${query}" 검색 결과 ${items.length}개` : `전체 오답 ${items.length}개`,
    [items.length, query]
  )

  const search = (event) => {
    event.preventDefault()
    const nextQuery = keyword.trim()
    setQuery(nextQuery)
    load(nextQuery, order)
  }

  const changeOrder = (value) => {
    setOrder(value)
    load(query, value)
  }

  // ── 다시 푼 기록 ──
  // 상세 화면을 열 때(다른 오답을 고를 때) 그 오답의 기록을 불러온다
  const selectedId = selectedItem ? selectedItem.id : null
  useEffect(() => {
    setAttempts([])
    if (!selectedId) return
    let cancelled = false
    getJson(`mistakes/${selectedId}/attempts`)
      .then((rows) => { if (!cancelled) setAttempts(Array.isArray(rows) ? rows : []) })
      .catch(() => { if (!cancelled) setAttempts([]) })
    return () => { cancelled = true }
  }, [selectedId])

  // 서버는 {mistake: 요약이 바뀐 오답, attempts: 기록 목록}을 돌려준다 → 상세 화면과 목록 카드에 같이 반영한다
  const applyAttemptResult = (data) => {
    setSelectedItem(data.mistake)
    setItems((current) => current.map((item) => item.id === data.mistake.id ? data.mistake : item))
    setAttempts(data.attempts)
  }

  // 상세 화면에서는 "다시 풀어서 맞혔다"만 기록한다. (또 틀린 것은 오답 등록 화면에서 고른 답·이유와 함께 기록)
  const markSolved = async () => {
    setActionError('')
    setAttemptBusy(true)
    try {
      const response = await api(`mistakes/${selectedItem.id}/attempts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_correct: true }),
      })
      if (!response.ok) throw new Error(await readError(response, '기록 실패'))
      applyAttemptResult(await response.json())
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '기록하지 못했습니다.')
    } finally {
      setAttemptBusy(false)
    }
  }

  const removeAttempt = async (attemptId) => {
    setActionError('')
    setAttemptBusy(true)
    try {
      const response = await api(`mistakes/${selectedItem.id}/attempts/${attemptId}`, { method: 'DELETE' })
      if (!response.ok) throw new Error(await readError(response, '삭제 실패'))
      applyAttemptResult(await response.json())
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '삭제하지 못했습니다.')
    } finally {
      setAttemptBusy(false)
    }
  }

  const beginEdit = async () => {
    setEditForm({
      paper_id: String(selectedItem.paper_id ?? ''),
      problem_no: selectedItem.problem_no || '',
      page: selectedItem.page ? String(selectedItem.page) : '',
      keyword: selectedItem.keyword || '',
      reason_type: selectedItem.reason_type || '',
      memo: selectedItem.memo || '',
      my_answer: selectedItem.my_answer || '',
      correct_answer: selectedItem.correct_answer || '',
    })
    // 목록을 불러오는 동안에도 지금 값이 비어 보이지 않게, 현재 값만 먼저 넣어 둔다.
    setEditOptions({
      papers: [{ id: selectedItem.paper_id, display_title: selectedItem.paper_title }],
      keywords: [],
      reasonTypes: selectedItem.reason_type ? [selectedItem.reason_type] : [],
      answerChoices: ['1', '2', '3', '4', '5'],
    })
    setActionError('')
    setNewImage('')
    setIsEditing(true)

    try {
      const [optionData, paperList, keywordList] = await Promise.all([getJson('options'), getJson('papers'), getJson('keywords')])
      setEditOptions({ papers: paperList, keywords: keywordList, reasonTypes: optionData.reason_types, answerChoices: optionData.answer_choices })
    } catch {
      setActionError('선택 목록을 불러오지 못했습니다. 서버가 켜져 있는지 확인해 주세요.')
    }
  }

  const pickNewImage = (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setActionError('이미지 파일만 선택할 수 있습니다.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => { setNewImage(String(reader.result)); setActionError('') }
    reader.readAsDataURL(file)
  }

  const saveEdit = async (event) => {
    event.preventDefault()
    setActionError('')
    const payload = {
      paper_id: Number(editForm.paper_id),
      problem_no: editForm.problem_no.trim(),
      page: editForm.page === '' ? 0 : Number(editForm.page), // 비우면 0 = 입력 안 함
      keyword: editForm.keyword.trim(),
      reason_type: editForm.reason_type,
      memo: editForm.memo.trim(),
      my_answer: editForm.my_answer,
      correct_answer: editForm.correct_answer,
    }
    if (newImage) payload.image_data = newImage
    const same = sameAnswerMessage(payload.my_answer, payload.correct_answer)
    if (same) {
      setActionError(same)
      return
    }
    if (!payload.paper_id || !payload.problem_no || !payload.keyword || !payload.reason_type || !Number.isInteger(payload.page) || payload.page < 0) {
      setActionError('문제지, 문제 번호, 키워드, 오답 이유를 입력하고 페이지는 1 이상의 정수로 입력하거나 비워 주세요.')
      return
    }
    try {
      const response = await api(`mistakes/${selectedItem.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) throw new Error(await readError(response, '수정 실패'))
      const updated = await response.json()
      setSelectedItem(updated)
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item))
      if (newImage) setImageVersion((v) => v + 1)
      setNewImage('')
      setIsEditing(false)
      await load(query, order)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '수정하지 못했습니다.')
    }
  }

  const deleteSelected = async () => {
    if (!window.confirm('이 오답 기록을 삭제할까요? 삭제한 기록은 복구할 수 없습니다.')) return
    setActionError('')
    try {
      const response = await api(`mistakes/${selectedItem.id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error(await readError(response, '삭제 실패'))
      setSelectedItem(null)
      setIsEditing(false)
      await load(query, order)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '삭제하지 못했습니다.')
    }
  }

  // 기록 카드를 선택하면 목록 대신 해당 기록의 상세 화면을 표시한다.
  if (selectedItem) {
    return (
      <section className="library">
        <div className="library-top">
          <div>
            <p className="eyebrow">오답 상세</p>
            <h2>{selectedItem.paper_title || '문제지'} · 문제 {selectedItem.problem_no || selectedItem.image_no || '-'}</h2>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {!isEditing && <button className="button primary press" onClick={beginEdit}>수정</button>}
            <button className="button press" onClick={deleteSelected} style={{ border: '1px solid #d66', color: '#b33' }}>삭제</button>
            <button className="button press" onClick={() => { setSelectedItem(null); setIsEditing(false); setActionError('') }}>← 목록으로</button>
          </div>
        </div>

        <article className="mistake-detail glass" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(260px, 0.8fr)', gap: 24, padding: 24, borderRadius: 20 }}>
          <div>
            {newImage ? (
              <img src={newImage} alt="새로 고른 문제 이미지" style={{ display: 'block', width: '100%', height: 'auto', maxHeight: '75vh', objectFit: 'contain', borderRadius: 12 }} />
            ) : (
              <AuthImage
                key={`${selectedItem.id}-${imageVersion}`}
                path={`mistakes/${selectedItem.id}/image`}
                alt={`${selectedItem.paper_title || '문제지'} 문제 이미지`}
                style={{ display: 'block', width: '100%', height: 'auto', maxHeight: '75vh', objectFit: 'contain', borderRadius: 12 }}
              />
            )}
            {isEditing && (
              <div className="image-edit">
                <label className="button press image-edit-pick">
                  {newImage ? '다른 이미지 고르기' : '이미지 바꾸기'}
                  <input type="file" accept="image/png,image/jpeg,image/webp" onChange={pickNewImage} hidden />
                </label>
                {newImage && <button type="button" className="button press" onClick={() => setNewImage('')}>원래 이미지로</button>}
                <p className="field-hint">{newImage ? '저장하면 이 이미지로 바뀌어요. (PNG·JPG·WEBP)' : '필요한 부분만 미리 잘라 둔 이미지를 고르면 돼요.'}</p>
              </div>
            )}
          </div>
          <div className="card-body">
            {isEditing ? (
              <form onSubmit={saveEdit} style={{ display: 'grid', gap: 12 }}>
                <h3>오답 기록 수정</h3>
                <label>문제지
                  <select required value={editForm.paper_id} onChange={(e) => setEditForm({ ...editForm, paper_id: e.target.value })}>
                    {editOptions.papers.map((paper) => (
                      <option key={paper.id} value={paper.id}>{paper.display_title}</option>
                    ))}
                  </select>
                </label>
                <label>문제 번호
                  <input required value={editForm.problem_no} onChange={(e) => setEditForm({ ...editForm, problem_no: e.target.value })} />
                </label>
                <label>페이지 (선택)
                  <input type="number" min="1" step="1" value={editForm.page} onChange={(e) => setEditForm({ ...editForm, page: e.target.value })} />
                </label>
                <label>핵심 키워드
                  <input required list="edit-keyword-options" autoComplete="off" value={editForm.keyword} onChange={(e) => setEditForm({ ...editForm, keyword: e.target.value })} />
                  <datalist id="edit-keyword-options">
                    {editOptions.keywords.map((item) => <option key={item.id} value={item.name} />)}
                  </datalist>
                </label>
                <label>오답 이유
                  <select required value={editForm.reason_type} onChange={(e) => setEditForm({ ...editForm, reason_type: e.target.value })}>
                    {editOptions.reasonTypes.map((reason) => (
                      <option key={reason} value={reason}>{reason}</option>
                    ))}
                  </select>
                </label>
                <AnswerChips label="내가 고른 답 (선택)" name="edit-my" value={editForm.my_answer} choices={editOptions.answerChoices} onChange={(next) => setEditForm({ ...editForm, my_answer: next })} />
                <AnswerChips label="정답 (선택)" name="edit-correct" value={editForm.correct_answer} choices={editOptions.answerChoices} onChange={(next) => setEditForm({ ...editForm, correct_answer: next })} />
                <label>메모 (선택)
                  <textarea rows="4" value={editForm.memo} onChange={(e) => setEditForm({ ...editForm, memo: e.target.value })} />
                </label>
                {actionError && <p role="alert" style={{ color: '#b33' }}>{actionError}</p>}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button className="button primary press" type="submit">저장</button>
                  <button className="button press" type="button" onClick={() => { setIsEditing(false); setActionError('') }}>취소</button>
                </div>
              </form>
            ) : (
              <>
                <div className="chip-row">
                  <span className="chip keyword">#{selectedItem.keyword || '키워드 없음'}</span>
                  {selectedItem.page > 0 && <span className="chip">p.{selectedItem.page}</span>}
                  <span className="chip">{selectedItem.reason_type || '-'}</span>
                </div>
                <h3>기록 정보</h3>
                <dl style={{ display: 'grid', gridTemplateColumns: '100px minmax(0, 1fr)', gap: '12px 8px', marginTop: 20 }}>
                  <dt>문제지</dt><dd style={{ margin: 0 }}>{selectedItem.paper_title || '-'}</dd>
                  <dt>문제 번호</dt><dd style={{ margin: 0 }}>{selectedItem.problem_no || selectedItem.image_no || '-'}</dd>
                  <dt>페이지</dt><dd style={{ margin: 0 }}>{selectedItem.page > 0 ? selectedItem.page : '-'}</dd>
                  <dt>핵심 키워드</dt><dd style={{ margin: 0 }}>{selectedItem.keyword || '-'}</dd>
                  <dt>오답 이유</dt><dd style={{ margin: 0 }}>{selectedItem.reason_type || '-'}</dd>
                  {selectedItem.my_answer && <><dt>내가 고른 답</dt><dd style={{ margin: 0 }}>{selectedItem.my_answer}</dd></>}
                  {selectedItem.correct_answer && <><dt>정답</dt><dd style={{ margin: 0 }}>{selectedItem.correct_answer}</dd></>}
                  <dt>등록일</dt><dd style={{ margin: 0 }}>{(selectedItem.created_at || '').slice(0, 10) || '-'}</dd>
                </dl>
                <div className="reason" style={{ marginTop: 24 }}>
                  <span>메모</span>
                  <p style={{ whiteSpace: 'pre-wrap' }}>{selectedItem.memo || '작성된 메모가 없습니다.'}</p>
                </div>
                <section className="retry-box" aria-labelledby="retry-title">
                  <h3 id="retry-title">다시 푼 기록</h3>
                  <p className="field-hint">
                    이 문제를 틀린 건 모두 {selectedItem.wrong_total}번이에요.
                    {selectedItem.attempt_count ? ` 다시 풀어서 맞힌 건 ${selectedItem.correct_count}번이에요.` : ''}
                    {' '}또 틀렸다면 “＋ 오답 등록”에서 같은 문제지와 문제 번호를 넣어 기록해 주세요.
                  </p>
                  <div className="retry-actions">
                    <button type="button" className="button primary press" disabled={attemptBusy} onClick={markSolved}>다시 풀어서 맞혔어요</button>
                  </div>
                  {attempts.length > 0 && (
                    <ul className="retry-list" aria-label="다시 푼 기록">
                      {attempts.map((attempt) => (
                        <li key={attempt.id}>
                          <span className={attempt.is_correct ? 'retry-result right' : 'retry-result wrong'}>{attempt.is_correct ? '맞음' : attempt.my_answer ? `틀림 · ${attempt.my_answer}번` : '틀림'}</span>
                          {attempt.reason_type && <span className="chip">{attempt.reason_type}</span>}
                          <span className="retry-date tabular">{(attempt.attempted_at || '').replace('T', ' ').slice(0, 16)}</span>
                          <button type="button" className="text-button" disabled={attemptBusy} onClick={() => removeAttempt(attempt.id)} aria-label={`${(attempt.attempted_at || '').slice(0, 10)} 기록 삭제`}>삭제</button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
                {actionError && <p role="alert" style={{ color: '#b33' }}>{actionError}</p>}
              </>
            )}
          </div>
        </article>
      </section>
    )
  }

  return (
    <section className="library">
      <div className="library-top">
        <div>
          {onBack && <button className="back-button" onClick={onBack}>← 이전</button>}
          <p className="eyebrow">{paper ? '문제지 오답' : '오답 아카이브'}</p>
          <h2>{paper ? paper.display_title : '기록을 모아, 다시 맞히는 흐름을 만드세요'}</h2>
        </div>
        <button className="button primary press" onClick={onRegister}>＋ 오답 등록</button>
      </div>

      <section className="trend-panel glass" aria-labelledby="trend-title">
        <div className="trend-heading">
          <div>
            <p className="eyebrow">등록 흐름</p>
            <h3 id="trend-title">날짜별 오답 등록 추이</h3>
            {visibleTrend.length > 0 && (
              <p className="trend-range tabular">
                {dateLabel(visibleTrend[0].date)} ~ {dateLabel(visibleTrend[visibleTrend.length - 1].date)}
                {canGoEarlier && ' · 왼쪽 끝에 마우스를 대면 이전 기록'}
              </p>
            )}
          </div>
          <strong className="trend-total tabular">
            총 {trend.reduce((sum, point) => sum + Number(point.count || 0), 0)}건
          </strong>
        </div>
        <div className="trend-chart">
          {canGoEarlier && (
            <button
              type="button"
              className="trend-edge left"
              aria-label="이전 날짜 보기"
              onMouseEnter={() => startTrendScroll(-1)}
              onMouseLeave={stopTrendScroll}
              onClick={() => stepTrend(-1)}
            >‹</button>
          )}
          {canGoLater && (
            <button
              type="button"
              className="trend-edge right"
              aria-label="최근 날짜 보기"
              onMouseEnter={() => startTrendScroll(1)}
              onMouseLeave={stopTrendScroll}
              onClick={() => stepTrend(1)}
            >›</button>
          )}
          {trend.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={visibleTrend} margin={{ top: 12, right: 12, left: -24, bottom: 0 }}>
                <XAxis dataKey="date" tickFormatter={dateLabel} tick={{ fill: cssVar('--color-muted'), fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: cssVar('--color-muted'), fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip
                  labelFormatter={dateLabel}
                  formatter={(value) => [`${value}건`, '등록 수']}
                  contentStyle={{ borderRadius: 'var(--radius-md)', border: 'var(--border-width) solid var(--glass-border)', background: 'var(--color-surface)' }}
                />
                <Line type="monotone" dataKey="count" stroke={cssVar('--chart-1')} strokeWidth={3} dot={{ r: 4, fill: cssVar('--chart-1') }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="chart-empty">아직 표시할 등록 추이가 없습니다.</p>
          )}
        </div>
      </section>

      <form className="search-box" onSubmit={search}>
        <span aria-hidden="true">⌕</span>
        <label className="visually-hidden" htmlFor="keyword-search">핵심 키워드 검색</label>
        <input id="keyword-search" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="예: 농도, 일률, 증감률" />
        <button className="button primary press search-button" type="submit">검색</button>
      </form>

      <div className="result-bar">
        <strong>{countLabel}</strong>
        <div className="result-actions">
          <label className="sort-control">
            정렬
            <select value={order} onChange={(event) => changeOrder(event.target.value)}>
              <option value="newest">등록 최신순</option>
              <option value="oldest">등록 오래된순</option>
            </select>
          </label>
          {query && (
            <button className="text-button" onClick={() => { setKeyword(''); setQuery(''); load('', order) }}>
              전체 보기
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="state-card">오답 기록을 불러오는 중입니다.</div>
      ) : error ? (
        <div className="state-card error">
          {error}
          <button className="text-button" onClick={() => load(query, order)}>다시 시도</button>
        </div>
      ) : items.length === 0 ? (
        <div className="state-card empty">
          <div className="empty-icon">◎</div>
          <h3>{query ? '검색한 키워드의 기록이 없습니다.' : '아직 등록된 오답이 없습니다.'}</h3>
          <p>문제 이미지를 잘라 등록하면 키워드와 등록일을 기준으로 다시 찾아볼 수 있습니다.</p>
          <button className="button primary press" onClick={onRegister}>첫 오답 등록하기</button>
        </div>
      ) : (
        <div className="mistake-grid">
          {items.map((item) => (
            <article
              className="mistake-card"
              key={item.id}
              role="button"
              tabIndex={0}
              aria-label={`${item.paper_title || '문제지'} 문제 ${item.problem_no || item.image_no || ''} 상세 보기`}
              onClick={() => setSelectedItem(item)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  setSelectedItem(item)
                }
              }}
              style={{ cursor: 'pointer' }}
            >
              {!query && (
                <AuthImage
                  path={`mistakes/${item.id}/image`}
                  alt={`${item.paper_title || '문제지'} ${item.problem_no || ''} 문제 이미지`}
                />
              )}
              <div className="card-body">
                <div className="chip-row">
                  <span className="chip keyword">#{item.keyword}</span>
                  {item.page > 0 && <span className="chip">p.{item.page}</span>}
                  <span className="chip">{item.reason_type}</span>
                  {answerSummary(item) && <span className="chip answer">{answerSummary(item)}</span>}
                  {retrySummary(item) && <span className={item.last_is_correct ? 'chip retry-right' : 'chip retry-wrong'}>{retrySummary(item)}</span>}
                </div>
                <h3>{item.paper_title}</h3>
                <p className="image-number tabular">문제 번호 {item.problem_no || item.image_no}</p>
                <p className="created-date">등록일 {(item.created_at || '').slice(0, 10)}</p>
                {item.memo && (
                  <div className="reason">
                    <span>메모</span>
                    <p>{item.memo}</p>
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
