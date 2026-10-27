import { useId, useState } from "react";
import { Link } from "react-router";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import { formatMinutes, formatReset, lectureSeconds, lecturesWord } from "./format";
import { emptyPlan, mergePlan, moveTo, plannedIds, type Plan } from "./plan";
import { PlanList } from "./PlanList";
import { planErrorOf, useQueuePlan, useWaiting, type Waiting } from "./queries";
import { useQuotaDialogParam } from "./useQuotaDialogParam";
import "./quota-dialog.css";

export function QuotaDialog() {
  const { open, setOpen } = useQuotaDialogParam();
  const waiting = useWaiting();
  const queuePlan = useQueuePlan();
  const toast = useToast();
  const [plan, setPlan] = useState<Plan>(emptyPlan);

  if (waiting.data && plan.source !== waiting.data) setPlan(mergePlan(plan, waiting.data));

  const close = () => {
    queuePlan.reset();
    setOpen(false);
  };

  const submit = () => {
    const ids = plannedIds(plan);
    queuePlan.mutate(ids, {
      onSuccess: () => {
        toast.show(`Отправили в обработку: ${ids.length} ${lecturesWord(ids.length)}`, "success");
        close();
      },
    });
  };

  const data = waiting.data;
  const hasLectures = data !== undefined && data.lectures.length > 0;

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Не хватает лимита"
      actions={
        hasLectures ? (
          <PlanActions plan={plan} waiting={data} pending={queuePlan.isPending} onLater={close} onSubmit={submit} />
        ) : (
          <Button variant="secondary" onClick={close}>
            Закрыть
          </Button>
        )
      }
    >
      <div className="quota-plan">
        {waiting.isPending && (
          <p className="quota-plan__status">
            <Spinner size="sm" label="Загружаем лекции" />
            Загружаем лекции, которые ждут лимита
          </p>
        )}
        {waiting.isError && !data && (
          <div className="quota-plan__status">
            <p className="quota-plan__alert">Не удалось загрузить лекции.</p>
            <Button variant="secondary" size="sm" onClick={() => waiting.refetch()}>
              Повторить
            </Button>
          </div>
        )}
        {data && !hasLectures && (
          <div className="quota-plan__empty">
            <h3>Ничего не ждёт лимита</h3>
            <p>Все лекции уже в очереди, в обработке или готовы.</p>
          </div>
        )}
        {hasLectures && (
          <PlanBody
            plan={plan}
            waiting={data}
            pending={queuePlan.isPending}
            error={queuePlan.isError ? planErrorOf(queuePlan.error) : null}
            onChange={setPlan}
            onLeave={close}
          />
        )}
      </div>
    </Dialog>
  );
}

function neededSeconds(plan: Plan, waiting: Waiting) {
  return waiting.lectures
    .filter((lecture) => plan.selected.includes(lecture.id))
    .reduce((sum, lecture) => sum + lectureSeconds(lecture.duration_sec), 0);
}

type PlanBodyProps = {
  plan: Plan;
  waiting: Waiting;
  pending: boolean;
  error: string | null;
  onChange: (plan: Plan) => void;
  onLeave: () => void;
};

function PlanBody({ plan, waiting, pending, error, onChange, onLeave }: PlanBodyProps) {
  const byId = new Map(waiting.lectures.map((lecture) => [lecture.id, lecture]));
  const lectures = plan.order.flatMap((id) => byId.get(id) ?? []);
  const needed = neededSeconds(plan, waiting);
  const available = waiting.available_sec;
  const over = needed > available;
  const share = available > 0 ? Math.min(100, (needed / available) * 100) : needed > 0 ? 100 : 0;
  const waitingCount = lectures.length - plan.selected.length;
  const optionsId = useId();

  const toggle = (id: string) =>
    onChange({
      ...plan,
      selected: plan.selected.includes(id) ? plan.selected.filter((item) => item !== id) : [...plan.selected, id],
    });

  return (
    <>
      <p className="quota-plan__lead">
        Осталось <strong>{formatMinutes(available)}</strong>. Отметьте, что обработать сейчас, и перетащите лекции в
        нужном порядке. Остальные подождут.
      </p>

      <div className={over ? "quota-plan__meter quota-plan__meter--over" : "quota-plan__meter"}>
        <div className="quota-plan__meter-head">
          <span>
            Выбрано {formatMinutes(needed)} из {formatMinutes(available)}
          </span>
          <span className="quota-plan__meter-note">
            {over ? `Больше остатка на ${formatMinutes(needed - available)}` : `Останется ${formatMinutes(available - needed)}`}
          </span>
        </div>
        <div className="quota-plan__track" aria-hidden="true">
          <div className="quota-plan__fill" style={{ width: `${share}%` }} />
        </div>
      </div>

      <PlanList
        lectures={lectures}
        selected={plan.selected}
        disabled={pending}
        onToggle={toggle}
        onMove={(id, index) => onChange({ ...plan, order: moveTo(plan.order, id, index) })}
      />

      {error && (
        <p className="quota-plan__alert" role="alert">
          {error}
        </p>
      )}

      <section className="quota-plan__options" aria-labelledby={optionsId}>
        <h3 id={optionsId}>{waitingCount > 0 ? "Что делать с остальными" : "Если часов не хватит"}</h3>
        <ul>
          <li>
            <span className="quota-plan__option-title">Дождаться обновления лимита</span>
            <span>
              Лимит обновится {formatReset(waiting.resets_at)}. Лекции останутся в этом списке.
            </span>
          </li>
          <li>
            <span className="quota-plan__option-title">Купить пакет часов</span>
            <span>Часы добавятся сразу после оплаты и не сгорают.</span>
            <Link to="/account#purchase" onClick={onLeave}>
              Перейти к покупке
            </Link>
          </li>
        </ul>
      </section>
    </>
  );
}

type PlanActionsProps = {
  plan: Plan;
  waiting: Waiting;
  pending: boolean;
  onLater: () => void;
  onSubmit: () => void;
};

function PlanActions({ plan, waiting, pending, onLater, onSubmit }: PlanActionsProps) {
  const count = plan.selected.length;
  const over = neededSeconds(plan, waiting) > waiting.available_sec;

  return (
    <>
      <Button variant="secondary" onClick={onLater} disabled={pending}>
        Позже
      </Button>
      <Button onClick={onSubmit} loading={pending} disabled={count === 0 || over}>
        {count === 0 ? "Ничего не выбрано" : "Обработать выбранные"}
      </Button>
    </>
  );
}
