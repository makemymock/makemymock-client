import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../../services/authService';
import { tokenStorage } from '../../utils/token';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { parseApiError } from '../../utils/validators';
import styles from './dashboard.module.css';

const Dashboard = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => tokenStorage.getUser());
  const [loading, setLoading] = useState(!user);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const fresh = await authService.me();
        if (!cancelled) {
          setUser(fresh);
          tokenStorage.setSession({ user: fresh });
        }
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load your account.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

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

        {user ? (
          <section className={styles.card}>
            <p className={styles.eyebrow}>Welcome back</p>
            <h1 className={styles.title}>{user.username}</h1>
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
