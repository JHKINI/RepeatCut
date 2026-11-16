import { useEffect, useState } from 'react'
import { api, getJson } from '../lib/api'

// 표본(데이터 개수)이 이 값보다 적으면 "아직 적어서 참고만 하세요" 안내를 보여준다
const SMALL_SAMPLE = 10

const percent = (ratio) => `${Math.round(ratio * 1000) / 10}%`

// 가로 막대 한 줄. width는 가장 큰 값을 100%로 한 비율이라 가장 많은 항목이 항상 가득 찬다.
function BarRow({ label, count, max, note }) {
  const width = max > 0 ? Math.round((count / max) * 100) : 0
  return (
    <li className="bar-row">
      <span className="bar-label">{label}</span>
      <span className="bar-track" aria-hidden="true"><span className="bar-fill" style={{ width: `${width}%` }} /></span>
      <span className="bar-value tabular">{count}건{note ? ` · ${note}` : ''}</span>
    </li>
  )
}

function AnswerBars({ title, data }) {
  const max = Math.max(0, ...data.items.map((item) => item.count))
  return (
    <div className="stat-box">
      <h4>{title}</h4>
      {data.sample === 0 ? (
        <p className="stat-empty">입력된 답이 아직 없어요.</p>
      ) : (
        <>
          <ul className="bar-list">
            {data.items.map((item) => <BarRow key={item.answer} label={`${item.answer}번`} count={item.count} max={max} />)}
          </ul>
          <p className="field-hint">입력된 답 {data.sample}건 기준</p>
        </>
      )}
    </div>
  )
}

// AI 학습 추천 카드. 버튼을 눌렀을 때만 서버에 요청한다. (AI 호출은 시간이 걸리고 횟수 제한이 있어서)
//  result: 서버가 준 {source, cached, notice, model, advice}
function StudyAdvice({ result, loading, error, onRequest }) {
  const advice = result && result.advice
  return (
    <section className="stat-box wide advice-box" aria-labelledby="stat-advice">
      <div className="advice-heading">
        <div>
          <h3 id="stat-advice">AI 학습 추천</h3>
          <p className="field-hint">아래 통계의 숫자와 키워드·문제지 이름만 AI에 보내요. 문제 이미지, 메모, 계정 정보는 보내지 않아요.</p>
        </div>
        <button type="button" className="button primary press" disabled={loading} onClick={onRequest}>
          {loading ? '추천을 만드는 중…' : result ? '다시 받기' : '추천 받기'}
        </button>
      </div>

      {error && <p className="inline-error" role="alert">{error}</p>}
      {result && result.notice && <p className="advice-notice" role="status">{result.notice}</p>}

      {advice && (
        <div className="advice-body">
          <p className="advice-summary">{advice.summary}</p>
          {advice.weak_points.length > 0 && (
            <ul className="advice-points">
              {advice.weak_points.map((point) => (
                <li key={point.title}>
                  <strong>{point.title}</strong>
                  {point.why && <span className="advice-why">{point.why}</span>}
                  {point.action && <span>{point.action}</span>}
                </li>
              ))}
            </ul>
          )}
          <h4>이렇게 공부해 보세요</h4>
          <ol className="advice-plan">
            {advice.plan.map((step) => <li key={step}>{step}</li>)}
          </ol>
          {advice.today && <p className="advice-today"><strong>오늘 할 일</strong> {advice.today}</p>}
          <p className="field-hint">
            {result.source === 'gemini'
              ? `Gemini(${result.model})가 통계를 보고 만든 추천이에요.${result.cached ? ' 통계가 그대로라서 지난번 추천을 다시 보여드려요.' : ''} AI의 조언이라 틀릴 수 있어요.`
              : '정해 둔 규칙으로 만든 추천이에요.'}
          </p>
        </div>
      )}
    </section>
  )
}

export function Stats() {
  const [papers, setPapers] = useState([])
  const [paperId, setPaperId] = useState('') // '' = 전체
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')
  // AI 학습 추천
  const [advice, setAdvice] = useState(null)
  const [adviceLoading, setAdviceLoading] = useState(false)
  const [adviceError, setAdviceError] = useState('')

  useEffect(() => {
    getJson('papers').then(setPapers).catch(() => setPapers([]))
  }, [])

  useEffect(() => {
    let cancelled = false
    setError('')
    // 문제지를 바꾸면 통계가 달라지므로, 앞에서 받은 추천은 지운다
    setAdvice(null)
    setAdviceError('')
    getJson(paperId ? `stats?paper_id=${paperId}` : 'stats')
      .then((data) => { if (!cancelled) setStats(data) })
      .catch(() => { if (!cancelled) setError('통계를 불러오지 못했습니다. 서버가 켜져 있는지 확인해 주세요.') })
    return () => { cancelled = true } // 문제지를 빠르게 바꿨을 때 늦게 도착한 이전 응답이 덮어쓰지 않게
  }, [paperId])

  const requestAdvice = async () => {
    const requestedPaperId = paperId
    setAdviceLoading(true)
    setAdviceError('')
    try {
      const response = await api(requestedPaperId ? `stats/advice?paper_id=${requestedPaperId}` : 'stats/advice', { method: 'POST' })
      if (!response.ok) throw new Error(`추천을 받지 못했습니다. (HTTP ${response.status})`)
      setAdvice(await response.json())
    } catch (err) {
      setAdviceError(err instanceof TypeError ? '서버에 연결하지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.' : err.message)
    } finally {
      setAdviceLoading(false)
    }
  }

  const keywordMax = stats ? Math.max(0, ...stats.keywords.map((item) => item.count)) : 0
  const reasonMax = stats ? Math.max(0, ...stats.reasons.map((item) => item.count)) : 0

  return (
    <section className="library stats-page">
      <div className="library-top">
        <div>
          <p className="eyebrow">통계</p>
          <h2>어디서, 왜 자주 틀리는지 한눈에 보세요</h2>
        </div>
        <label className="sort-control">
          문제지
          <select aria-label="통계 문제지 선택" value={paperId} onChange={(event) => setPaperId(event.target.value)}>
            <option value="">전체</option>
            {papers.map((paper) => <option key={paper.id} value={paper.id}>{paper.display_title}</option>)}
          </select>
        </label>
      </div>

      {error ? (
        <div className="state-card error">{error}</div>
      ) : !stats ? (
        <div className="state-card">통계를 불러오는 중입니다.</div>
      ) : stats.total === 0 ? (
        <div className="state-card empty">
          <div className="empty-icon">◎</div>
          <h3>아직 집계할 오답이 없어요.</h3>
          <p>오답을 등록하면 키워드와 오답 이유별로 모아서 보여드려요.</p>
        </div>
      ) : (
        <>
          <p className="stats-total" role="status">
            총 오답 <strong className="tabular">{stats.total}</strong>건
            {stats.total < SMALL_SAMPLE && <span className="small-sample"> · 표본이 적어요. 오답이 쌓일수록 정확해져요.</span>}
          </p>

          <StudyAdvice result={advice} loading={adviceLoading} error={adviceError} onRequest={requestAdvice} />

          <div className="stats-grid">
            <section className="stat-box" aria-labelledby="stat-keywords">
              <h3 id="stat-keywords">키워드별 오답 (많은 순)</h3>
              <ul className="bar-list">
                {stats.keywords.map((item) => <BarRow key={item.keyword_id} label={`#${item.name}`} count={item.count} max={keywordMax} note={percent(item.count / stats.total)} />)}
              </ul>
            </section>

            <section className="stat-box" aria-labelledby="stat-reasons">
              <h3 id="stat-reasons">오답 이유별 (또 틀린 것 포함)</h3>
              <ul className="bar-list">
                {stats.reasons.map((item) => <BarRow key={item.reason_type} label={item.reason_type} count={item.count} max={reasonMax} note={percent(item.ratio)} />)}
              </ul>
            </section>
          </div>

          <section className="stat-box wide" aria-labelledby="stat-matrix">
            <h3 id="stat-matrix">자주 틀린 키워드는 어떤 이유로 틀렸을까?</h3>
            <div className="table-scroll">
              <table className="stat-table">
                <thead>
                  <tr>
                    <th scope="col">키워드</th>
                    {stats.keyword_reasons.reason_types.map((reason) => <th scope="col" key={reason}>{reason}</th>)}
                    <th scope="col">합계</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.keyword_reasons.rows.map((row) => (
                    <tr key={row.keyword_id}>
                      <th scope="row">#{row.name}</th>
                      {stats.keyword_reasons.reason_types.map((reason) => (
                        <td key={reason} className={row.counts[reason] ? 'has-count tabular' : 'tabular'}>{row.counts[reason] || '·'}</td>
                      ))}
                      <td className="tabular"><strong>{row.total}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="field-hint">오답이 많은 상위 {stats.keyword_reasons.rows.length}개 키워드만 보여줘요.</p>
          </section>

          <section className="stat-box wide" aria-labelledby="stat-papers">
            <h3 id="stat-papers">문제지별 오답</h3>
            <div className="table-scroll">
              <table className="stat-table">
                <thead>
                  <tr><th scope="col">문제지</th><th scope="col">오답 수</th><th scope="col">문항 수</th><th scope="col">오답률</th></tr>
                </thead>
                <tbody>
                  {stats.papers.map((paper) => (
                    <tr key={paper.paper_id}>
                      <th scope="row">{paper.display_title}</th>
                      <td className="tabular">{paper.mistake_count}</td>
                      <td className="tabular">{paper.total_questions ?? '-'}</td>
                      <td className="tabular">{paper.wrong_rate === null ? '문항 수 미입력' : percent(paper.wrong_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="field-hint">오답률 = 오답 수 ÷ 문항 수. 문제지의 “수정”에서 문항 수를 넣어 두면 계산돼요.</p>
          </section>

          <section className="stat-box wide" aria-labelledby="stat-retry">
            <h3 id="stat-retry">다시 풀기</h3>
            {stats.retry.attempts === 0 ? (
              <p className="stat-empty">아직 다시 푼 기록이 없어요. 또 틀린 문제는 오답 등록에서, 다시 풀어서 맞힌 문제는 오답 상세에서 기록해 보세요.</p>
            ) : (
              <>
                <ul className="bar-list">
                  <BarRow label="다시 맞힘" count={stats.retry.solved} max={stats.total} />
                  <BarRow label="또 틀림" count={stats.retry.still_wrong} max={stats.total} />
                  <BarRow label="아직 안 풂" count={stats.retry.not_retried} max={stats.total} />
                </ul>
                <p className="field-hint">
                  오답마다 가장 최근에 다시 푼 결과 기준. 다시 푼 {stats.retry.attempts}번 중 {stats.retry.correct}번 맞혔어요 ({percent(stats.retry.correct_rate)}).
                </p>
                {stats.retry.repeat_wrong.length > 0 && (
                  <div className="table-scroll">
                    <table className="stat-table">
                      <caption className="visually-hidden">다시 풀어도 틀린 문제</caption>
                      <thead>
                        <tr><th scope="col">다시 풀어도 틀린 문제</th><th scope="col">키워드</th><th scope="col">틀린 횟수</th><th scope="col">틀린 이유</th><th scope="col">고른 답</th><th scope="col">정답</th></tr>
                      </thead>
                      <tbody>
                        {stats.retry.repeat_wrong.map((item) => (
                          <tr key={item.mistake_id}>
                            <th scope="row">{item.paper_title} · {item.problem_no}번</th>
                            <td>#{item.keyword}</td>
                            <td className="has-count tabular">{item.wrong_total}</td>
                            <td>{item.wrong_reasons.length ? item.wrong_reasons.join(' → ') : '-'}</td>
                            <td className="tabular">{item.wrong_answers.length ? item.wrong_answers.join(' → ') : '-'}</td>
                            <td className="tabular">{item.correct_answer || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </section>

          <div className="stats-grid">
            <AnswerBars title="내가 자주 고른 오답 번호 (또 틀린 것 포함)" data={stats.answers.my_answer} />
            <AnswerBars title="정답 번호 분포" data={stats.answers.correct_answer} />
          </div>
        </>
      )}
    </section>
  )
}
