import { useMemo } from 'react';
import MatchingEditor from '../MatchingEditor/MatchingEditor';
import MarkdownText from '../../common/MarkdownText/MarkdownText';
import styles from './QuestionViewer.module.css';

// Renders one question of any supported type. Owns NO state; reports
// changes via onChange(newAnswer).
//
// AnswerShape per type:
//   single_correct (or passage sub-Q) → { selected_option: 'A' }
//   multi_correct                     → { selected_options: ['A','C'] }
//   integer                           → { integer_answer: '42' }
//   matching                          → { matching: { L1: 'R2', L2: 'R1' } }
const QuestionViewer = ({
  question,
  index,
  total,
  answer,
  onChange,
  readOnly = false,
  correctAnswer,
  isCorrect,
}) => {
  const qtype = question.passage_sub_index != null
    ? 'single_correct'
    : question.question_type;

  const correctSet = useMemo(() => {
    if (correctAnswer == null) return null;
    if (Array.isArray(correctAnswer)) return new Set(correctAnswer.map((x) => String(x).toUpperCase()));
    if (typeof correctAnswer === 'string') return new Set([correctAnswer.toUpperCase()]);
    return null;
  }, [correctAnswer]);

  return (
    <article className={styles.viewer}>
      <header className={styles.head}>
        <span className={styles.qIndex}>Q{index + 1}<span className={styles.qTotal}>/{total}</span></span>
        <div className={styles.tags}>
          {question.passage_id != null ? (
            <span className={`${styles.tag} ${styles.passage}`}>
              Passage · part {question.passage_sub_index + 1}/{question.passage_sub_total}
            </span>
          ) : null}
          <span className={`${styles.tag} ${styles[`diff_${(question.difficulty || 'medium').toLowerCase()}`]}`}>
            {question.difficulty}
          </span>
          <span className={`${styles.tag} ${styles.type}`}>
            {prettyType(question.question_type, question.passage_sub_index != null)}
          </span>
        </div>
      </header>

      {question.passage_text ? (
        <section className={styles.passage}>
          <p className={styles.passageEyebrow}>Passage</p>
          <MarkdownText text={question.passage_text} />
        </section>
      ) : null}

      <section className={styles.body}>
        <MarkdownText text={question.question_text} />
      </section>

      {(qtype === 'single_correct') && (
        <OptionList
          options={question.options}
          multi={false}
          selected={answer?.selected_option ? [answer.selected_option] : []}
          onToggle={(key) => onChange({ selected_option: key })}
          readOnly={readOnly}
          correctSet={correctSet}
        />
      )}

      {qtype === 'multi_correct' && (
        <OptionList
          options={question.options}
          multi
          selected={answer?.selected_options || []}
          onToggle={(key) => {
            const cur = new Set(answer?.selected_options || []);
            if (cur.has(key)) cur.delete(key);
            else cur.add(key);
            onChange({ selected_options: Array.from(cur).sort() });
          }}
          readOnly={readOnly}
          correctSet={correctSet}
        />
      )}

      {qtype === 'integer' && (
        <IntegerInput
          value={answer?.integer_answer ?? ''}
          onChange={(v) => onChange({ integer_answer: v })}
          readOnly={readOnly}
          correctAnswer={readOnly ? correctAnswer : null}
          isCorrect={isCorrect}
        />
      )}

      {qtype === 'matching' && (
        <MatchingEditor
          left={question.left_column || []}
          right={question.right_column || []}
          value={answer?.matching || {}}
          onChange={(m) => onChange({ matching: m })}
          readOnly={readOnly}
          correctMapping={readOnly ? correctAnswer : null}
        />
      )}
    </article>
  );
};

function prettyType(t, isPassageSub) {
  if (isPassageSub) return 'Passage sub-question';
  switch (t) {
    case 'single_correct': return 'Single correct';
    case 'multi_correct': return 'Multiple correct';
    case 'integer': return 'Integer answer';
    case 'matching': return 'Matching';
    case 'passage': return 'Passage';
    default: return t;
  }
}

const OptionList = ({ options, multi, selected, onToggle, readOnly, correctSet }) => {
  const selSet = new Set(selected.map((s) => String(s).toUpperCase()));
  return (
    <ul className={styles.optionList} role={multi ? 'group' : 'radiogroup'}>
      {options.map((opt) => {
        const key = String(opt.key).toUpperCase();
        const isSelected = selSet.has(key);
        const isCorrect = correctSet?.has(key);
        const showCorrect = readOnly && isCorrect;
        const showWrong = readOnly && isSelected && !isCorrect;
        const cls = [
          styles.option,
          isSelected ? styles.optionOn : '',
          showCorrect ? styles.optionCorrect : '',
          showWrong ? styles.optionWrong : '',
        ].filter(Boolean).join(' ');
        return (
          <li key={opt.key}>
            <button
              type="button"
              role={multi ? 'checkbox' : 'radio'}
              aria-checked={isSelected}
              className={cls}
              onClick={readOnly ? undefined : () => onToggle(key)}
              disabled={readOnly}
            >
              <span className={styles.optionKey}>{opt.key}</span>
              <span className={styles.optionText}>
                <MarkdownText text={opt.text} inline />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
};

const IntegerInput = ({ value, onChange, readOnly, correctAnswer, isCorrect }) => {
  return (
    <div className={styles.integerWrap}>
      <input
        type="text"
        inputMode="decimal"
        className={`${styles.integerInput} ${readOnly ? (isCorrect ? styles.integerCorrect : styles.integerWrong) : ''}`}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value.replace(/[^0-9eE+\-.]/g, ''))}
        placeholder="Numeric answer"
        readOnly={readOnly}
        aria-label="Integer answer"
      />
      {readOnly && correctAnswer != null ? (
        <p className={styles.integerHint}>
          Correct answer: <strong>{String(correctAnswer)}</strong>
        </p>
      ) : null}
    </div>
  );
};

export default QuestionViewer;
