// 답(1~5번)을 칩으로 고르는 입력. 이미 고른 칩을 다시 누르면 선택이 풀린다. (답은 선택 입력)
// 예전에 서술형 같은 값이 저장돼 있으면 그 값도 칩으로 보여줘서 지울 수 있게 한다.
const CIRCLED = { 1: '①', 2: '②', 3: '③', 4: '④', 5: '⑤' }

export function AnswerChips({ label, name, value, onChange, choices }) {
  const labelId = `answer-label-${name}`
  const shown = value && !choices.includes(value) ? [...choices, value] : choices

  return (
    <div className="field-group">
      <span className="field-label" id={labelId}>{label}</span>
      <div className="choice-row" role="group" aria-labelledby={labelId}>
        {shown.map((choice) => (
          <button
            type="button"
            key={choice}
            className="choice-chip"
            aria-pressed={value === choice}
            aria-label={`${label} ${choice}번`}
            onClick={() => onChange(value === choice ? '' : choice)}
          >
            {CIRCLED[choice] || choice}
          </button>
        ))}
      </div>
    </div>
  )
}

export const SAME_ANSWER_TEXT = '내가 고른 답과 정답이 같아요. 틀린 문제라면 둘이 달라야 해요.'

// 내가 고른 답과 정답이 같으면 안내할 문장 (같지 않거나 하나라도 비어 있으면 빈 문자열)
export function sameAnswerMessage(myAnswer, correctAnswer) {
  const mine = (myAnswer || '').trim().toLowerCase()
  const correct = (correctAnswer || '').trim().toLowerCase()
  return mine && correct && mine === correct ? SAME_ANSWER_TEXT : ''
}
