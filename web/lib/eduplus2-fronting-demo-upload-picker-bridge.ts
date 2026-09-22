const RESOURCE_UPLOAD_LABEL = "选择图片、音频、视频或文档文件";
const RESOURCE_UPLOAD_LABEL_ID = "eduplus2-resource-upload-label";
const BRIDGE_MANAGED_ATTRIBUTE = "data-eduplus2-upload-picker-managed";
const NATIVE_PICKER_CLASS =
  "block w-full cursor-pointer rounded-2xl border border-teal-200 bg-white px-3 py-2 text-xs font-semibold normal-case tracking-normal text-teal-950 shadow-sm file:mr-4 file:cursor-pointer file:rounded-xl file:border-0 file:bg-teal-700 file:px-4 file:py-2 file:text-xs file:font-black file:text-white hover:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500 dark:border-teal-900 dark:bg-slate-950 dark:text-teal-50 dark:file:bg-teal-300 dark:file:text-slate-950";

function normalizeText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

function inputLabelText(input: HTMLInputElement, rootDocument: Document): string {
  const labelledBy = input.getAttribute("aria-labelledby");
  const labelledByText = labelledBy
    ? normalizeText(rootDocument.getElementById(labelledBy)?.textContent)
    : "";
  const nativeLabels = Array.from(input.labels ?? [])
    .map((label) => normalizeText(label.textContent))
    .join(" ");
  return normalizeText(`${labelledByText} ${nativeLabels}`);
}

function ensureUploadLabelId(input: HTMLInputElement): string {
  const existing = input.getAttribute("aria-labelledby");
  if (existing) return existing;

  const label = input.labels?.[0];
  if (label) {
    if (!label.id) {
      label.id = RESOURCE_UPLOAD_LABEL_ID;
    }
    return label.id;
  }
  return RESOURCE_UPLOAD_LABEL_ID;
}

function removeProxyChooserButtons(input: HTMLInputElement): void {
  const nativeLabel = input.labels?.[0];
  const scope =
    nativeLabel?.contains(input) && nativeLabel.parentElement
      ? nativeLabel.parentElement
      : (input.parentElement ?? input.ownerDocument.body);
  for (const button of Array.from(scope.querySelectorAll<HTMLButtonElement>("button"))) {
    if (normalizeText(button.textContent) === "选择文件") {
      button.remove();
    }
  }
}

function repairInput(input: HTMLInputElement): void {
  const labelId = ensureUploadLabelId(input);
  if (input.getAttribute("aria-labelledby") !== labelId) {
    input.setAttribute("aria-labelledby", labelId);
  }
  if (input.getAttribute(BRIDGE_MANAGED_ATTRIBUTE) !== "true") {
    input.setAttribute(BRIDGE_MANAGED_ATTRIBUTE, "true");
  }
  if (input.className !== NATIVE_PICKER_CLASS) {
    input.className = NATIVE_PICKER_CLASS;
  }
  removeProxyChooserButtons(input);
}

function repairExistingInputs(rootDocument: Document): void {
  for (const input of Array.from(
    rootDocument.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  )) {
    const isBridgeManaged = input.getAttribute(BRIDGE_MANAGED_ATTRIBUTE) === "true";
    if (!isBridgeManaged && !inputLabelText(input, rootDocument).includes(RESOURCE_UPLOAD_LABEL)) {
      continue;
    }
    repairInput(input);
  }
}

export function installEduPlus2ResourceUploadPickerBridge(
  rootDocument: Document = document,
): () => void {
  repairExistingInputs(rootDocument);

  const MutationObserverCtor = rootDocument.defaultView?.MutationObserver;
  if (!MutationObserverCtor) {
    return () => undefined;
  }

  const observer = new MutationObserverCtor(() => {
    repairExistingInputs(rootDocument);
  });
  observer.observe(rootDocument.body, {
    attributes: true,
    attributeFilter: ["class", "aria-labelledby"],
    childList: true,
    subtree: true,
  });

  return () => observer.disconnect();
}
