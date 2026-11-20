import { html, nothing, type TemplateResult } from "lit";

export {
  mdiAccountGroupOutline,
  mdiAccountMultipleOutline,
  mdiAccountOutline,
  mdiAlertCircleOutline,
  mdiAlertOutline,
  mdiArchiveArrowDownOutline,
  mdiArchiveArrowUpOutline,
  mdiArchiveOutline,
  mdiArrowLeft,
  mdiBellCheckOutline,
  mdiBellRemoveOutline,
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
  mdiImageOffOutline,
  mdiInboxOutline,
  mdiMagnify,
  mdiMenu,
  mdiMessageBadgeOutline,
  mdiOpenInNew,
  mdiPlay,
  mdiPuzzleOutline,
  mdiRefresh,
  mdiReplay,
  mdiRobotOutline,
  mdiScriptTextOutline,
  mdiSelectAll,
  mdiSelectRemove,
  mdiSendCheckOutline,
  mdiSortClockAscendingOutline,
  mdiSortClockDescendingOutline,
  mdiSpeaker,
  mdiSwapHorizontal,
  mdiTagOutline,
  mdiUnfoldLessHorizontal,
  mdiUnfoldMoreHorizontal,
  mdiVideoOutline,
  mdiVolumeHigh,
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
