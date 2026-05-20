import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../../services/authService';
import { profileService } from '../../services/profileService';
import { tokenStorage } from '../../utils/token';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { parseApiError } from '../../utils/validators';
import styles from './dashboard.module.css';

const TARGET_EXAM_LABEL = {
  jee_main: 'JEE Main',
  jee_advanced: 'JEE Advanced',
  boards: 'Boards',
  other: 'Other',
};

const Dashboard = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => tokenStorage.getUser());
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [me, myProfile] = await Promise.all([
          authService.me(),
          profileService.getMyProfile().catch((err) => {
            if (err?.response?.status === 404) return null;
            throw err;
          }),
        ]);

        if (cancelled) return;

        setUser(me);
        tokenStorage.setSession({ user: me });

        if (myProfile === null) {
          navigate('/profile/setup', { replace: true });
          return;
        }

        setProfile(myProfile);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load your account.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

  const displayName = user?.username || 'there';

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.dot} aria-hidden="true" />
          <span className={styles.brandText}>MAKE MY MOCK</span>
        </div>
        <button type="button" className={styles.logout} onClick={handleLogout}>
          Sign out
        </button>
      </header>

      <main className={styles.main}>
        {loading ? <Loader /> : null}
        {error ? <ErrorMessage message={error} /> : null}

        {!loading && user ? (
          <section className={styles.card}>
            <p className={styles.eyebrow}>Welcome back</p>
            <h1 className={styles.title}>Hi, {displayName} 👋</h1>
            <p className={styles.subtitle}>{user.email}</p>

            <dl className={styles.meta}>
              <div className={styles.metaItem}>
                <dt>Status</dt>
                <dd>{user.is_verified ? 'Verified' : 'Pending verification'}</dd>
              </div>
              <div className={styles.metaItem}>
                <dt>Account</dt>
                <dd>{user.is_active ? 'Active' : 'Inactive'}</dd>
              </div>
              {profile?.target_exam ? (
                <div className={styles.metaItem}>
                  <dt>Target exam</dt>
                  <dd>{TARGET_EXAM_LABEL[profile.target_exam] || profile.target_exam}</dd>
                </div>
              ) : null}
              {profile?.class_grade ? (
                <div className={styles.metaItem}>
                  <dt>Class</dt>
                  <dd>{profile.class_grade === 'dropper' ? 'Dropper' : `Class ${profile.class_grade}`}</dd>
                </div>
              ) : null}
            </dl>

            <p className={styles.tip}>
              You're signed in. Tests, analytics and personalized practice will appear here soon.
            </p>
          </section>
        ) : null}
      </main>
    </div>
  );
};

export default Dashboard;
