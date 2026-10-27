import { createPortal } from "react-dom";
import { Cheatsheet, DefinitionList, TicketList } from "./ExamSheetContent";
import type { Definition, ExamSheet } from "./queries";

type ExamSheetPrintProps = {
  courseTitle: string;
  sheet: ExamSheet;
  definitions: Definition[];
};

export function ExamSheetPrint({ courseTitle, sheet, definitions }: ExamSheetPrintProps) {
  return createPortal(
    <article className="exam-print">
      <header className="exam-print__head">
        <h1>{courseTitle || "Памятка к экзамену"}</h1>
        {courseTitle && <p>Памятка к экзамену</p>}
      </header>
      <section className="exam-print__section">
        <h2>Билеты</h2>
        <TicketList tickets={sheet.tickets} />
      </section>
      <section className="exam-print__section">
        <h2>Определения</h2>
        <DefinitionList definitions={definitions} />
      </section>
      <section className="exam-print__section">
        <h2>Шпаргалка</h2>
        <Cheatsheet source={sheet.cheatsheet_md} />
      </section>
    </article>,
    document.body,
  );
}
