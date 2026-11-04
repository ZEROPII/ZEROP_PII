import { Loader2, LogIn } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { LogoMark } from '../components/brand/Logo';
import { useAuth } from '../state/AuthContext';

const ROLES: [string, string][] = [
  ['의료진', 'EMR 외래 목록에서 진료 중인 환자를 열고, 비슷한 과거 사례를 진료 지원 AI에 묻습니다. 환자를 알아볼 수 있는 값은 범위로 바뀌거나 비공개로 보입니다.'],
  ['보안 담당자', '의료진 대화마다 재식별 위험과 판정 근거를 보고, 세부 정보 요청에 답하며, 원문 열람은 사유와 함께 감사 기록에 남깁니다.'],
];

/** 로그인 (python -m medicloak). 계정의 역할이 들어갈 화면을 정한다. */
export function LoginPage() {
  const auth = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    userRef.current?.focus();
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('아이디와 비밀번호를 모두 넣으세요.');
      return;
    }
    setBusy(true);
    setError(null);
    const msg = await auth.login(username.trim(), password);
    setBusy(false);
    if (msg) {
      setError(msg);
      setPassword('');
    }
  }

  return (
    <div className="grid min-h-dvh bg-page text-ink md:grid-cols-[minmax(0,1.05fr)_minmax(360px,1fr)]">
      <section aria-label="MediCloak 소개" className="flex flex-col justify-between gap-10 border-b border-line bg-surface px-6 py-8 md:border-b-0 md:border-r md:px-12 md:py-12">
        <div className="flex items-center gap-3">
          <LogoMark size={40} />
          <span className="text-xl font-extrabold tracking-[-0.02em] text-iris-text">MediCloak</span>
        </div>
        <div className="max-w-[34rem]">
          <h1 className="text-[28px] font-extrabold leading-[1.25] tracking-[-0.03em] md:text-[36px]">
            의료 AI의 답이
            <br />
            환자 한 명을 가리키지 않게
          </h1>
          <p className="mt-4 text-[15px] leading-7 text-ink-2">
            진료 지원 AI가 비슷한 과거 사례를 보여 줄 때, 대화 전체에서 나온 단서를 사례마다 모아 셉니다. 그대로 답하면 해당 환자가 다섯 명 아래로 줄어드는 값은 넓은 범위로 바꾸거나 가립니다.
          </p>
          <dl className="mt-8 space-y-4">
            {ROLES.map(([role, text]) => (
              <div key={role} className="grid grid-cols-[88px_1fr] gap-3 border-t border-line pt-4">
                <dt className="text-[13px] font-bold text-ink">{role}</dt>
                <dd className="text-[13px] leading-6 text-ink-2">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
        <p className="text-xs leading-5 text-ink-3">Synthea 합성 환자 576명으로 만든 가상 EMR 위에서 돕니다. 실제 환자 정보는 없습니다.</p>
      </section>

      <section aria-label="로그인" className="flex items-center justify-center px-6 py-10">
        <form onSubmit={(e) => void submit(e)} className="w-full max-w-[360px]" noValidate>
          <h2 className="text-xl font-bold tracking-[-0.02em]">로그인</h2>
          <p className="mt-1 text-[13px] text-ink-3">병원에서 받은 계정으로 들어갑니다.</p>
          {auth.notice && !error && (
            <p role="status" className="mt-4 rounded-control bg-surface-2 px-3 py-2 text-[13px] text-ink-2">
              {auth.notice}
            </p>
          )}
          <label htmlFor="login-user" className="mt-6 block text-[13px] font-semibold text-ink-2">
            아이디
          </label>
          <input
            id="login-user"
            ref={userRef}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            className="mt-1.5 h-11 w-full rounded-control border border-line-input bg-surface px-3 text-[15px] text-ink outline-none focus:border-focus"
          />
          <label htmlFor="login-pw" className="mt-4 block text-[13px] font-semibold text-ink-2">
            비밀번호
          </label>
          <input
            id="login-pw"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="mt-1.5 h-11 w-full rounded-control border border-line-input bg-surface px-3 text-[15px] text-ink outline-none focus:border-focus"
          />
          <p role="alert" aria-live="assertive" className="mt-3 min-h-[20px] text-[13px] text-danger-text">
            {error}
          </p>
          <button type="submit" disabled={busy} className="btn-primary mt-2 h-11 w-full text-[15px]">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <LogIn className="h-4 w-4" aria-hidden />}
            로그인
          </button>
          <p className="mt-6 text-xs leading-5 text-ink-3">
            처음 켠 서버의 데모 계정(의료진 doctor1 · doctor2, 보안 담당자 privacy1)과 비밀번호는 서버 폴더의{' '}
            <code className="rounded bg-surface-2 px-1 py-px font-mono text-[11px]">runs/medicloak/demo_accounts.txt</code>에 있습니다.
          </p>
        </form>
      </section>
    </div>
  );
}
