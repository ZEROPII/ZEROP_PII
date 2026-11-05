import { Clock3, Eye, EyeOff, KeyRound, Loader2, Lock, LogIn, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { LogoMark } from '../components/brand/Logo';
import { useBackendInfo } from '../hooks/useBackendInfo';
import { useAuth } from '../state/AuthContext';

const ROLES: [string, string][] = [
  ['의료진', '외래 환자를 열고 비슷한 과거 사례를 진료 지원 AI에 묻습니다.'],
  ['보안 담당자', '대화마다 재식별 위험을 관제하고, 세부 정보 요청을 검토해 승인합니다.'],
];

/**
 * 과거 진료 기록 한 장을 값 없이 그린 표. 답이 나가기 전 값마다 하는 세 가지 처리(그대로 · 범위로 바꿈 · 비공개)를
 * 막대 모양으로만 보인다. 실제 기록이나 예시 값은 넣지 않는다.
 */
type Cell = 'plain' | 'range' | 'lock';
const LEDGER: { label: number; value: number; kind: Cell }[] = [
  { label: 26, value: 58, kind: 'plain' },
  { label: 20, value: 30, kind: 'range' },
  { label: 30, value: 46, kind: 'plain' },
  { label: 18, value: 40, kind: 'lock' },
  { label: 24, value: 66, kind: 'plain' },
  { label: 22, value: 26, kind: 'range' },
  { label: 28, value: 50, kind: 'lock' },
];

function Swatch({ kind, width }: { kind: Cell; width: number | string }) {
  if (kind === 'plain') return <span className="block h-2.5 rounded-[3px] bg-emr-chrome-text opacity-70" style={{ width }} aria-hidden />;
  if (kind === 'range')
    return <span className="block h-2.5 rounded-[3px] border-[1.5px] border-[#5fd3c7]" style={{ width }} aria-hidden />;
  return <span className="login-hatch block h-2.5 rounded-[3px]" style={{ width }} aria-hidden />;
}

function Ledger() {
  return (
    <figure className="max-w-[26rem]" aria-label="값마다의 처리: 그대로, 범위로 바꿈, 비공개">
      <div className="rounded-[10px] border border-emr-chrome-line bg-emr-chrome-hover px-5 py-4">
        <div className="mb-3.5 flex items-center gap-2 border-b border-emr-chrome-line pb-3">
          <span className="h-2 w-2 rounded-full bg-[#5fd3c7]" aria-hidden />
          <span className="text-xs font-semibold text-emr-chrome-muted">과거 진료 기록</span>
        </div>
        <ul className="space-y-3" aria-hidden>
          {LEDGER.map((r, i) => (
            <li key={i} className="grid grid-cols-[30%_1fr] items-center gap-4">
              <span className="block h-1.5 rounded-full bg-emr-chrome-line" style={{ width: `${r.label * 2.4}%` }} />
              <span className="flex items-center gap-2">
                {r.kind === 'lock' && <Lock className="h-3 w-3 shrink-0 text-emr-chrome-muted" strokeWidth={2.4} />}
                <Swatch kind={r.kind} width={`${r.value}%`} />
              </span>
            </li>
          ))}
        </ul>
      </div>
      <figcaption className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-emr-chrome-muted">
        <span className="flex items-center gap-1.5">
          <Swatch kind="plain" width={18} />
          그대로
        </span>
        <span className="flex items-center gap-1.5">
          <Swatch kind="range" width={18} />
          범위로 바꿈
        </span>
        <span className="flex items-center gap-1.5">
          <Swatch kind="lock" width={18} />
          비공개
        </span>
      </figcaption>
    </figure>
  );
}

/** 로그인 (python -m medicloak). 계정의 역할이 들어갈 화면을 정한다. */
export function LoginPage() {
  const auth = useAuth();
  const backend = useBackendInfo();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);
  const release = backend?.release?.replace(/^medicloak-release-/, '');

  useEffect(() => {
    userRef.current?.focus();
  }, []);

  function capsOf(e: KeyboardEvent<HTMLInputElement>) {
    setCaps(e.getModifierState?.('CapsLock') ?? false);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('아이디와 비밀번호를 모두 입력하세요.');
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

  const field =
    'mt-1.5 h-11 w-full rounded-control border border-line-input bg-surface px-3 text-[15px] text-ink outline-none transition-colors focus:border-focus focus:ring-2 focus:ring-iris-tint';

  return (
    <div data-app="emr" className="grid min-h-dvh bg-page text-ink md:grid-cols-[minmax(0,1fr)_minmax(400px,0.92fr)]">
      <section
        aria-label="MediCloak"
        className="flex flex-col gap-8 bg-emr-chrome px-6 py-7 text-emr-chrome-text md:justify-between md:border-r md:border-emr-chrome-line md:px-12 md:py-11"
      >
        <div className="flex items-center gap-3">
          <LogoMark size={34} className="text-[#5fd3c7]" />
          <div className="leading-tight">
            <p className="text-[17px] font-extrabold tracking-[-0.02em]">MediCloak</p>
            <p className="text-xs text-emr-chrome-muted">진료 지원 AI 개인정보 보호</p>
          </div>
        </div>

        <div className="max-w-[30rem]">
          <h1 className="text-[24px] font-extrabold leading-[1.3] tracking-[-0.03em] md:text-[32px]">
            과거 사례는 진료에 쓰고,
            <br />
            그 환자는 드러나지 않게
          </h1>
          <p className="mt-4 hidden text-[15px] leading-7 text-emr-chrome-muted md:block">
            진료 지원 AI의 답이 화면에 나가기 전에 대화 전체에서 나온 단서를 사례마다 모아 셉니다. 과거 환자를 좁힐 수 있는 값은 범위로 바꾸거나 가립니다.
          </p>
          <div className="mt-8 hidden md:block">
            <Ledger />
          </div>
        </div>

        <div className="hidden md:block">
          <dl className="grid max-w-[30rem] gap-3">
            {ROLES.map(([role, text]) => (
              <div key={role} className="grid grid-cols-[84px_1fr] gap-3 border-t border-emr-chrome-line pt-3">
                <dt className="text-[13px] font-bold">{role}</dt>
                <dd className="text-[13px] leading-6 text-emr-chrome-muted">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-label="로그인" className="flex flex-col px-6 py-10 md:px-10">
        <div className="flex flex-1 items-center justify-center">
          <form onSubmit={(e) => void submit(e)} className="w-full max-w-[380px]" noValidate>
            <h2 className="text-[22px] font-bold tracking-[-0.02em]">로그인</h2>
            <p className="mt-1 text-[13px] text-ink-3">병원에서 발급한 계정으로 로그인합니다.</p>
            {auth.notice && !error && (
              <p role="status" className="mt-5 rounded-control border border-line bg-surface-2 px-3 py-2 text-[13px] text-ink-2">
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
              className={field}
            />
            <label htmlFor="login-pw" className="mt-4 block text-[13px] font-semibold text-ink-2">
              비밀번호
            </label>
            <div className="relative">
              <input
                id="login-pw"
                type={show ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={capsOf}
                onKeyUp={capsOf}
                autoComplete="current-password"
                aria-describedby={caps ? 'login-caps' : undefined}
                className={`${field} pr-11`}
              />
              <button
                type="button"
                onClick={() => setShow((v) => !v)}
                aria-label={show ? '비밀번호 숨기기' : '비밀번호 보기'}
                aria-pressed={show}
                className="absolute right-1.5 top-[calc(50%+3px)] grid h-8 w-8 -translate-y-1/2 place-items-center rounded-control text-ink-3 hover:bg-surface-2 hover:text-ink"
              >
                {show ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
              </button>
            </div>
            <p id="login-caps" aria-live="polite" className="text-xs text-caution-text">
              {caps ? <span className="mt-1.5 block">Caps Lock이 켜져 있습니다.</span> : null}
            </p>
            <p role="alert" aria-live="assertive" className="mt-2 min-h-[20px] text-[13px] text-danger-text">
              {error}
            </p>
            <button type="submit" disabled={busy} className="btn-primary mt-2 h-11 w-full text-[15px]">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <LogIn className="h-4 w-4" aria-hidden />}
              로그인
            </button>

            <ul className="mt-8 space-y-2.5 border-t border-line pt-5 text-xs leading-5 text-ink-3">
              <li className="flex gap-2.5">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                접속 기록과 환자 조회 내역은 감사 기록에 남습니다.
              </li>
              <li className="flex gap-2.5">
                <Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                60분 동안 사용하지 않으면 자동으로 로그아웃됩니다.
              </li>
              <li className="flex gap-2.5">
                <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                계정 발급과 비밀번호 초기화는 병원 시스템 관리자에게 문의하세요.
              </li>
            </ul>
          </form>
        </div>
        <p className="mt-8 text-center text-[11px] text-ink-3 md:text-right">MediCloak{release ? ` · 판정 규칙 ${release}` : ''}</p>
      </section>
    </div>
  );
}
