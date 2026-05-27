import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import MarkdownText from '../../components/common/MarkdownText/MarkdownText';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './browse.module.css';

const PAGE_SIZE = 20;

const DIFFICULTIES = [
  { value: '', label: 'All levels' },
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
];

const TYPES = [
  { value: '', label: 'All types' },
  { value: 'single_correct', label: 'Single' },
  { value: 'multi_correct', label: 'Multiple' },
  { value: 'integer', label: 'Integer' },
  { value: 'matching', label: 'Matching' },
  { value: 'passage', label: 'Passage' },
];

const STATUSES = [
  { value: '', label: 'All' },
  { value: 'true', label: 'Attempted' },
  { value: 'false', label: 'Not attempted' },
];

const MARKED_STATUSES = [
  { value: '', label: 'All' },
  { value: 'true', label: 'Marked' },
  { value: 'false', label: 'Not marked' },
];

function prettyType(t) {
  switch (t) {
    case 'single_correct': return 'Single';
    case 'multi_correct': return 'Multiple';
    case 'integer': return 'Integer';
    case 'matching': return 'Matching';
    case 'passage': return 'Passage';
    default: return t;
  }
}

// Status glyph + label for a row, with attempted taking precedence over viewed.
function rowStatus(item) {
  if (item.attempted && item.performance) {
    const s = item.performance.status;
    if (s === 'correct') return { cls: 'stCorrect', glyph: '✓', label: 'Solved' };
    if (s === 'partial') return { cls: 'stPartial', glyph: '◐', label: 'Partial' };
    return { cls: 'stWrong', glyph: '✗', label: 'Wrong' };
  }
  if (item.viewed) return { cls: 'stViewed', glyph: '👁', label: 'Viewed' };
  return { cls: 'stTodo', glyph: '○', label: 'Todo' };
}

const BrowsePanel = ({ notebookMode = false }) => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [catalog, setCatalog] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Filters are read straight from the URL so the view is shareable and Back
  // from a problem page restores it exactly.
  const subject = searchParams.get('subject') || '';
  const chapter = searchParams.get('chapter') || '';
  const topic = searchParams.get('topic') || '';
  const difficulty = searchParams.get('difficulty') || '';
  const qtype = searchParams.get('qtype') || '';
  const attempted = searchParams.get('attempted') || '';
  // In notebook mode the list is always the marked set; otherwise it follows
  // the Marked chip in the URL.
  const markedParam = searchParams.get('marked') || '';
  const marked = notebookMode ? 'true' : markedParam;
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);

  // Search box is debounced into the URL.
  const [searchInput, setSearchInput] = useState(searchParams.get('q') || '');

  // Patch the URL, always keeping tab=browse, resetting to page 1 unless the
  // change IS the page.
  const patch = (changes, { resetPage = true } = {}) => {
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set('tab', 'browse');
      for (const [k, v] of Object.entries(changes)) {
        if (v === '' || v === null || v === undefined) p.delete(k);
        else p.set(k, v);
      }
      if (resetPage && !('page' in changes)) p.delete('page');
      return p;
    });
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cat = await mockTestService.getCatalog();
        if (!cancelled) setCatalog(cat);
      } catch {
        /* filters still work without the cascading selects */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Debounce the search box → URL `q`.
  useEffect(() => {
    const handle = setTimeout(() => {
      const cur = searchParams.get('q') || '';
      if (searchInput !== cur) patch({ q: searchInput.trim() });
    }, 350);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const q = searchParams.get('q') || '';

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await mockTestService.browseQuestions({
          subject, chapter, topic, difficulty,
          question_type: qtype, attempted, marked, search: q,
          page, page_size: PAGE_SIZE,
        });
        if (!cancelled) setData(res);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load questions.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [subject, chapter, topic, difficulty, qtype, attempted, marked, q, page]);

  // Cascading select options from the catalog tree.
  const subjects = useMemo(() => catalog?.subjects || [], [catalog]);
  const chapters = useMemo(() => {
    const s = subjects.find((x) => x.name === subject);
    return s ? s.chapters : [];
  }, [subjects, subject]);
  const topics = useMemo(() => {
    const c = chapters.find((x) => x.name === chapter);
    return c ? c.topics : [];
  }, [chapters, chapter]);

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const openQuestion = (id) => {
    // Carry the full filter query so the problem page can build prev/next
    // and the list panel, and so Back returns to this exact view. In notebook
    // mode, inject marked=true so the problem page's prev/next stay within the
    // notebook set.
    const p = new URLSearchParams(searchParams);
    if (marked) p.set('marked', marked);
    navigate(`/tests/browse/${id}?${p.toString()}`);
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.filters}>
        <div className={styles.searchRow}>
          <input
            type="search"
            className={styles.search}
            placeholder="Search question text…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label="Search questions"
          />
        </div>

        <div className={styles.selectRow}>
          <select
            className={styles.select}
            value={subject}
            onChange={(e) => patch({ subject: e.target.value, chapter: '', topic: '' })}
            aria-label="Subject"
          >
            <option value="">All subjects</option>
            {subjects.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>

          <select
            className={styles.select}
            value={chapter}
            disabled={!subject}
            onChange={(e) => patch({ chapter: e.target.value, topic: '' })}
            aria-label="Chapter"
          >
            <option value="">All chapters</option>
            {chapters.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>

          <select
            className={styles.select}
            value={topic}
            disabled={!chapter}
            onChange={(e) => patch({ topic: e.target.value })}
            aria-label="Topic"
          >
            <option value="">All topics</option>
            {topics.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
          </select>
        </div>

        <div className={styles.chipGroups}>
          <ChipGroup
            options={DIFFICULTIES}
            value={difficulty}
            onChange={(v) => patch({ difficulty: v })}
          />
          <ChipGroup
            options={TYPES}
            value={qtype}
            onChange={(v) => patch({ qtype: v })}
          />
          <ChipGroup
            options={STATUSES}
            value={attempted}
            onChange={(v) => patch({ attempted: v })}
          />
          {!notebookMode ? (
            <ChipGroup
              options={MARKED_STATUSES}
              value={markedParam}
              onChange={(v) => patch({ marked: v })}
            />
          ) : null}
        </div>
      </div>

      <div className={styles.resultBar}>
        <span>{total} question{total === 1 ? '' : 's'}{notebookMode ? ' in your notebook' : ''}</span>
        {(subject || chapter || topic || difficulty || qtype || attempted || q || (!notebookMode && markedParam)) ? (
          <button
            type="button"
            className={styles.clearBtn}
            onClick={() => {
              setSearchInput('');
              const reset = { subject: '', chapter: '', topic: '', difficulty: '', qtype: '', attempted: '', q: '' };
              if (!notebookMode) reset.marked = '';
              patch(reset);
            }}
          >
            Clear filters
          </button>
        ) : null}
      </div>

      {loading ? <Loader /> : null}
      {error ? <ErrorMessage message={error} /> : null}

      {!loading && !error && data ? (
        data.items.length === 0 ? (
          <div className={styles.empty}>
            {notebookMode ? (
              <>
                <h3>Your notebook is empty.</h3>
                <p>Save questions from Browse or after a test (the 🏷️ button) to revise them here.</p>
              </>
            ) : (
              <>
                <h3>No questions match these filters.</h3>
                <p>Try widening the difficulty, type, or topic.</p>
              </>
            )}
          </div>
        ) : (
          <ul className={styles.list}>
            {data.items.map((item) => {
              const st = rowStatus(item);
              return (
                <li key={item.question_id}>
                  <button
                    type="button"
                    className={styles.row}
                    onClick={() => openQuestion(item.question_id)}
                  >
                    <span className={`${styles.status} ${styles[st.cls]}`} title={st.label} aria-label={st.label}>
                      {st.glyph}
                    </span>
                    <span className={styles.rowMain}>
                      <span className={styles.rowText}>
                        <MarkdownText text={item.question_text} inline />
                      </span>
                      <span className={styles.rowMeta}>
                        {item.subject} · {item.chapter} · {item.topic}
                      </span>
                    </span>
                    <span className={styles.rowTags}>
                      {item.marked && !notebookMode ? (
                        <span className={styles.markFlag} title="In your notebook" aria-label="In your notebook">🔖</span>
                      ) : null}
                      <span className={`${styles.tag} ${styles.tagType}`}>{prettyType(item.question_type)}</span>
                      <span className={`${styles.tag} ${styles[`diff_${(item.difficulty || 'medium').toLowerCase()}`]}`}>
                        {item.difficulty}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )
      ) : null}

      {!loading && total > PAGE_SIZE ? (
        <div className={styles.pager}>
          <button
            type="button"
            className={styles.pagerBtn}
            disabled={page <= 1}
            onClick={() => patch({ page: String(page - 1) }, { resetPage: false })}
          >
            ‹ Prev
          </button>
          <span className={styles.pagerInfo}>Page {page} of {totalPages}</span>
          <button
            type="button"
            className={styles.pagerBtn}
            disabled={page >= totalPages}
            onClick={() => patch({ page: String(page + 1) }, { resetPage: false })}
          >
            Next ›
          </button>
        </div>
      ) : null}
    </div>
  );
};

const ChipGroup = ({ options, value, onChange }) => (
  <div className={styles.chips} role="group">
    {options.map((o) => (
      <button
        key={o.value || 'all'}
        type="button"
        className={`${styles.chip} ${value === o.value ? styles.chipOn : ''}`}
        aria-pressed={value === o.value}
        onClick={() => onChange(o.value)}
      >
        {o.label}
      </button>
    ))}
  </div>
);

export default BrowsePanel;
