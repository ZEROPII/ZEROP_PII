import { Lock, MailQuestion, MessageSquareReply, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { useAuth } from '../state/AuthContext';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-5 first:border-t-0 first:pt-0">
      <h2 className="text-[17px] font-bold tracking-[-0.015em] text-ink">{title}</h2>
      <div className="mt-2 space-y-2 text-sm leading-7 text-ink-2">{children}</div>
    </section>
  );
}

const WORDS: [string, string][] = [
  ['사례', 'AI가 찾아 보여 준 비슷한 과거 환자 기록 하나. 이름이나 환자 번호 없이 사례 1, 사례 2로 부릅니다.'],
  ['범위', '정확한 값 대신 보여 드린 넓은 값. 예를 들어 정확한 날짜 대신 연도, 정확한 나이 대신 나이대입니다.'],
  ['비공개', '그대로 알려 드리면 특정 환자를 알아볼 수 있어 MediCloak이 답에서 뺀 값. 표시를 누르면 어느 사례의 무엇인지와 까닭이 보입니다.'],
  ['AI에 보내지 않음', 'MediCloak이 과거 사례 기록을 진료 지원 AI에 넘기기 전에 가린 값. AI도 그 값을 모르므로 답에 (비공개)로 나옵니다.'],
  ['세부 정보 제한', '지금까지 나온 내용만으로도 환자를 좁힐 수 있는 사례. 새로 묻는 세부 값은 범위로 보이거나 비공개일 수 있습니다.'],
  ['사례 노트', '그 사례에 대해 지금까지 답에 나온 내용을 한 장으로 모은 것. 값마다 그 값을 꺼낸 질문으로 돌아갈 수 있습니다.'],
];

/** 의료진용 보호 안내: 숫자 없이, 무엇이 왜 가려지고 필요하면 어떻게 요청하는지. 기준값은 보안 담당자 '보호 정책'에 있다. */
export function GuidePage() {
  const product = useAuth().status === 'user';
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <article className="mx-auto max-w-2xl space-y-6 px-4 py-6 md:px-6 md:py-8">
        <header>
          <p className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-iris-text">
            <ShieldCheck className="h-4 w-4" aria-hidden /> MediCloak 보호 적용
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-[-0.025em] text-ink">진료 지원 AI의 개인정보 보호</h1>
          <p className="mt-2 text-sm leading-7 text-ink-2">
            이 AI는 비슷한 과거 사례의 기록을 찾아 답합니다. MediCloak은 답이 화면에 나오기 전에, 그 답과 앞선 대화를 함께 보고 특정 환자를 알아볼 수
            있게 되는 값이 있는지 확인합니다. 진료에 필요한 내용은 그대로 두고, 환자를 좁히는 값만 넓히거나 뺍니다.
          </p>
        </header>

        <Section title="무엇을 막는지">
          <p>
            비슷한 사례 하나는 병원 과거 기록의 환자 한 명입니다. 그 사람의 진단이나 처방을 보는 것만으로는 누구인지 알 수 없습니다. 위험은 답이 쌓이면서
            그 사람을 다른 환자와 구별할 수 있게 될 때 생깁니다. 예를 들어 '90대 여성, 2018년 3월 급성 기관지염'까지는 같은 조건의 환자가 여럿이지만,
            정확한 나이와 날짜가 더해지면 한 사람만 남을 수 있습니다.
          </p>
          <p>
            MediCloak은 사례마다 지금까지 나온 내용을 모아, 같은 조건의 환자가 기준보다 적어지게 만드는 값을 범위로 바꾸거나 뺍니다. 그와 별도로 나이는 5세
            구간, 날짜는 월 단위보다 자세히 보이지 않고, 거주 지역처럼 조회 목적(처방 · 시술 · 경과 참고)에 쓰지 않는 정보는 답에서 뺍니다.
          </p>
          <p>
            여러 사례의 공통점이나 차이는 입력칸 위 '묻는 범위'를 '찾은 사례 전체'로 바꿔 한 번에 물어보세요. 사례 목록의 '비교'는 지금까지 답에 나온 값을
            사례별 표로 보여 줍니다.
          </p>
        </Section>

        <Section title="답에 보이는 표시">
          <dl className="space-y-3">
            <div className="grid grid-cols-[136px_minmax(0,1fr)] items-baseline gap-3">
              <dt className="font-medium text-ink">Acute bronchitis</dt>
              <dd>표시가 없는 값은 기록 그대로입니다.</dd>
            </div>
            <div className="grid grid-cols-[136px_minmax(0,1fr)] items-baseline gap-3">
              <dt className="font-medium text-ink">
                <span className="range-value">90~94세</span>
                <span className="range-tag">범위</span>
              </dt>
              <dd>정확한 값 대신 한 단계 넓은 범위로 바꾼 값입니다. 뜻은 같고 덜 자세합니다.</dd>
            </div>
            <div className="grid grid-cols-[136px_minmax(0,1fr)] items-baseline gap-3">
              <dt>
                <span className="lock-token">
                  <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
                  비공개
                </span>
              </dt>
              <dd>그대로 알려 드리면 그 환자가 누구인지 알 수 있게 되는 값이라 MediCloak이 답에서 뺐습니다. '처방 약 비공개'처럼 무엇을 뺐는지 붙고, 같은 사례의 다른 값이 보이면 '다른 처방 약 비공개'로 보입니다. 답의 나머지는 그대로입니다.</dd>
            </div>
            <div className="grid grid-cols-[136px_minmax(0,1fr)] items-baseline gap-3">
              <dt>
                <span className="lock-token">
                  <Lock className="h-3 w-3" strokeWidth={2.2} aria-hidden />
                  AI에 보내지 않음
                </span>
              </dt>
              <dd>과거 사례 기록을 진료 지원 AI에 넘기기 전에 가린 값입니다. AI도 그 값을 모르므로 답에 (비공개)로 쓰고, 화면은 이 표시로 바꿔 보입니다.</dd>
            </div>
          </dl>
          <p>표시를 누르면 그 자리에 무엇을 왜 바꿨는지 설명이 뜨고, 답 아래에는 사례마다 바뀐 항목이 한 줄씩 보입니다. 표시는 진료 지원 AI가 아니라 MediCloak이 붙입니다.</p>
          <p>
            같은 질문도 대화가 이어지면 다르게 보일 수 있습니다. 앞선 답에서 나온 내용과 합쳐 환자가 좁혀지는지까지 함께 보기 때문입니다.
          </p>
        </Section>

        <Section title="세부 정보가 꼭 필요할 때">
          <p className="flex gap-2">
            <MailQuestion className="mt-1.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
            <span>
              답 아래 <strong className="font-semibold text-ink">세부 정보 요청</strong>을 누르고 사유를 적어 보내면 개인정보 보호 담당자에게 갑니다. 답장은
              오른쪽 아래 <strong className="font-semibold text-ink">보호 담당자 창</strong>에 오고, 머리줄 알림에도 표시됩니다.
            </span>
          </p>
          <p className="flex gap-2">
            <MessageSquareReply className="mt-1.5 h-4 w-4 shrink-0 text-iris-text" aria-hidden />
            <span>보호 담당자가 질문한 목적을 물어볼 때도 있습니다(확인 요청). 대화 위에 안내가 뜨면 같은 창에서 답장해 주세요.</span>
          </p>
        </Section>

        <Section title="남는 기록">
          <p>
            질문과 답, 세부 정보 요청과 답장은 감사 기록에 남고 개인정보 보호 담당자가 확인할 수 있습니다. 보호 담당자가 가린 원래 값을 열어 볼 때도 사유를
            남겨야 하며, 그 열람도 기록됩니다.
          </p>
          {product && (
            <p>
              내 담당 환자의 차트를 연 일도 환자마다 접근 기록에 남습니다. 담당이 아닌 환자는 목록에 나오지 않으며, 협진이나 당직처럼 꼭 봐야 할 때만
              '담당 외 환자 열기'에서 사유를 적고 정해진 시간 동안 엽니다. 그 열람은 보호 담당자가 나중에 검토합니다.
            </p>
          )}
        </Section>

        <Section title="화면에서 쓰는 말">
          <dl className="divide-y divide-line rounded-control border border-line bg-surface">
            {WORDS.map(([t, d]) => (
              <div key={t} className="grid grid-cols-[136px_minmax(0,1fr)] gap-3 px-4 py-3">
                <dt className="font-semibold text-ink">{t}</dt>
                <dd className="text-[13px] leading-6 text-ink-2">{d}</dd>
              </div>
            ))}
          </dl>
        </Section>
      </article>
    </div>
  );
}
