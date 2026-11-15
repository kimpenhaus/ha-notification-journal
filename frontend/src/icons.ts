import { html, nothing, type TemplateResult } from "lit";

export {
  mdiAccountGroupOutline,
  mdiAccountMultipleOutline,
  mdiAccountOutline,
  mdiAlertCircleOutline,
  mdiArchiveArrowDownOutline,
  mdiArchiveArrowUpOutline,
  mdiArchiveOutline,
  mdiArrowLeft,
  mdiBellCheckOutline,
  mdiBellOutline,
  mdiBullhornOutline,
  mdiCalendarClockOutline,
  mdiChartBar,
  mdiCellphone,
  mdiChatOutline,
  mdiCheck,
  mdiCheckAll,
  mdiCheckCircle,
  mdiCheckboxBlankCircleOutline,
  mdiCheckboxMultipleMarkedOutline,
  mdiChevronDown,
  mdiChevronLeft,
  mdiChevronRight,
  mdiClose,
  mdiFilterRemoveOutline,
  mdiFlashOutline,
  mdiHelpCircleOutline,
  mdiHomeAssistant,
  mdiInboxOutline,
  mdiMagnify,
  mdiMenu,
  mdiMessageBadgeOutline,
  mdiOpenInNew,
  mdiPuzzleOutline,
  mdiRefresh,
  mdiRobotOutline,
  mdiScriptTextOutline,
  mdiSelectAll,
  mdiSelectRemove,
  mdiSendCheckOutline,
  mdiSortClockAscendingOutline,
  mdiSortClockDescendingOutline,
  mdiSpeaker,
  mdiSwapHorizontal,
  mdiUnfoldLessHorizontal,
  mdiUnfoldMoreHorizontal,
} from "@mdi/js";

export function icon(path: string, label?: string): TemplateResult {
  return html`<svg
    class="icon"
    viewBox="0 0 24 24"
    aria-hidden=${label ? "false" : "true"}
    aria-label=${label ?? nothing}
  >
    <path d=${path}></path>
  </svg>`;
}
