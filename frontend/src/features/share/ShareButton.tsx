import { useRef, useState } from "react";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import { errorDetail, matchesTarget, useCreateShare, useRevokeShare, useShares, type ShareTarget } from "./queries";
import "./share.css";

type ShareButtonProps = {
  target: ShareTarget;
  title: string;
};

export function ShareButton({ target, title }: ShareButtonProps) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    requestAnimationFrame(() => trigger.current?.focus());
  }

  return (
    <>
      <Button ref={trigger} variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Поделиться
      </Button>
      {open && <ShareDialog target={target} title={title} onClose={close} />}
    </>
  );
}

function ShareDialog({ target, title, onClose }: ShareButtonProps & { onClose: () => void }) {
  const toast = useToast();
  const linkInput = useRef<HTMLInputElement>(null);
  const shares = useShares();
  const create = useCreateShare(target);
  const revoke = useRevokeShare();
  const isCourse = "courseId" in target;
  const share = shares.data?.find((item) => matchesTarget(item, target));
  const pending = create.isPending || revoke.isPending;

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      toast.show("Ссылка скопирована", "success");
    } catch {
      linkInput.current?.select();
      toast.show("Не получилось скопировать. Ссылка выделена, скопируйте её вручную", "error");
    }
  }

  function createLink() {
    create.mutate(undefined, { onSuccess: () => toast.show("Ссылка создана", "success") });
  }

  function revokeLink(token: string) {
    revoke.mutate(token, {
      onSuccess: () => toast.show("Ссылка отозвана. По ней больше ничего не откроется", "success"),
    });
  }

  let body;
  if (shares.isPending) {
    body = (
      <div className="share__status">
        <Spinner size="sm" label="Проверяем ссылку" />
        <span>Проверяем, есть ли ссылка</span>
      </div>
    );
  } else if (shares.isError) {
    body = (
      <div className="share__status share__status--error" role="alert">
        <span>Не получилось загрузить ссылки.</span>
        <Button variant="ghost" size="sm" onClick={() => void shares.refetch()} loading={shares.isFetching}>
          Повторить
        </Button>
      </div>
    );
  } else if (share) {
    body = (
      <>
        <div className="share__link">
          <Field label="Ссылка для чтения">
            {(control) => (
              <Input
                {...control}
                ref={linkInput}
                readOnly
                value={share.url}
                onFocus={(event) => event.currentTarget.select()}
              />
            )}
          </Field>
          <Button onClick={() => void copy(share.url)}>Скопировать</Button>
        </div>
        <p className="share__note">
          Кто получит ссылку, увидит {isCourse ? "курс" : "лекцию"} без входа, но ничего не сможет изменить.
        </p>
        <div className="share__revoke">
          <Button variant="ghost" size="sm" className="share__revoke-button" loading={revoke.isPending} disabled={pending} onClick={() => revokeLink(share.token)}>
            Отозвать ссылку
          </Button>
          <span className="share__note">Ссылка сразу перестанет открываться.</span>
        </div>
        {revoke.isError && (
          <p className="share__error" role="alert">
            Не получилось отозвать ссылку. Попробуйте ещё раз.
          </p>
        )}
      </>
    );
  } else {
    body = (
      <>
        <p>
          {isCourse
            ? "По ссылке откроются название, описание и список лекций курса. Лекции внутри откроются, если ими тоже поделиться."
            : "По ссылке откроются видео, конспект, главы и расшифровка. Входить в аккаунт не нужно, изменить ничего нельзя."}
        </p>
        {create.isError && (
          <p className="share__error" role="alert">
            {errorDetail(create.error) ?? "Не получилось создать ссылку. Попробуйте ещё раз."}
          </p>
        )}
      </>
    );
  }

  return (
    <Dialog
      open
      dismissible={!pending}
      title={`Поделиться: «${title}»`}
      onClose={onClose}
      actions={
        share || shares.isPending || shares.isError ? (
          <Button variant="secondary" disabled={pending} onClick={onClose}>
            Готово
          </Button>
        ) : (
          <>
            <Button variant="secondary" disabled={pending} onClick={onClose}>
              Отмена
            </Button>
            <Button loading={create.isPending} onClick={createLink}>
              Создать ссылку
            </Button>
          </>
        )
      }
    >
      <div className="share">{body}</div>
    </Dialog>
  );
}
