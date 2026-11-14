import { html, nothing, type TemplateResult } from "lit";

export {
  mdiAccountGroupOutline,
  mdiAccountMultipleOutline,
  mdiAccountOutline,
  mdiAlertCircleOutline,
  mdiArchiveArrowDownOutline,
  mdiArchiveArrowUpOutline,
  mdiArchiveOutline,
  mdiBellCheckOutline,
  mdiBellOutline,
  mdiBullhornOutline,
  mdiCalendarClockOutline,
  mdiCellphone,
  mdiChatOutline,
  mdiCheckAll,
  mdiCheckCircle,
  mdiCheckboxBlankCircleOutline,
  mdiCheckboxMultipleMarkedOutline,
  mdiChevronDown,
  mdiClose,
  mdiFilterRemoveOutline,
  mdiHelpCircleOutline,
  mdiHomeAssistant,
  mdiInboxOutline,
  mdiMagnify,
  mdiMenu,
  mdiMessageBadgeOutline,
  mdiOpenInNew,
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
