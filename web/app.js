const statusLabels = {
  draft: "等待导入文件",
  checking_files: "正在检查文件",
  ready: "可以开始核对",
  reconciling: "正在核对",
  needs_attention: "有数据待处理",
  completed: "本期已完成",
  reopened: "已重新打开",
  failed: "处理失败",
};

const ordinaryReconciliationTab = "__ordinary_settlement__";
const refundReconciliationTab = "__refund_settlement__";
const wideReconciliationTab = "__wide_reconciliation__";
const platformBalanceTab = "__platform_balance__";
const pendingSettlementTab = "__pending_settlement__";
const supplementaryResultTabs = {
  __cross_month__: { resultType: "cross_month", summaryKey: "crossMonth", label: "订单与结算" },
  __after_sale__: { resultType: "after_sale", summaryKey: "afterSales", label: "售后状态" },
  __cost_link__: { resultType: "cost", summaryKey: "costs", label: "成本关联" },
  __other_fund__: { resultType: "other_fund", summaryKey: "otherFunds", label: "其他收支" },
};

const wideColumnGroups = [
  {
    label: "核对结论",
    className: "wide-group-result",
    columns: [
      ["status", "状态", "status"],
      ["sceneLabels", "业务场景", "list"],
      ["subOrderId", "子订单号", "text"],
      ["differenceCents", "核对差额", "money"],
      ["reason", "差异原因", "longText"],
      ["suggestion", "下一步", "longText"],
      ["resultCount", "结果数", "count"],
      ["action", "操作", "action"],
    ],
  },
  {
    label: "订单",
    className: "wide-group-order",
    columns: [
      ["mainOrderId", "主订单号", "text"],
      ["sku", "货号", "text"],
      ["quantity", "数量", "count"],
      ["orderStatus", "订单状态", "text"],
      ["submittedAt", "提交时间", "datetime"],
      ["unitPriceCents", "商品单价", "money"],
      ["shippingCents", "运费", "money"],
      ["orderPayableCents", "订单应付", "money"],
      ["platformDiscountCents", "平台优惠", "money"],
      ["merchantDiscountCents", "商家优惠", "money"],
      ["creatorDiscountCents", "达人优惠", "money"],
      ["expectedMerchantReceivableCents", "预计商家应收", "money"],
      ["receivableDifferenceCents", "应收与结算差额", "money"],
    ],
  },
  {
    label: "售后",
    className: "wide-group-after-sale",
    columns: [
      ["afterSaleCount", "售后数", "count"],
      ["afterSaleTypes", "售后类型", "list"],
      ["afterSaleStatuses", "售后状态", "list"],
      ["afterSaleRequestedRefundCents", "申请退款金额", "money"],
      ["afterSaleRefundCents", "成功退款金额", "money"],
      ["afterSaleLatestAt", "最新售后时间", "datetime"],
    ],
  },
  {
    label: "结算",
    className: "wide-group-settlement",
    columns: [
      ["settlementCount", "结算数", "count"],
      ["settlementTypes", "结算类型", "list"],
      ["settlementLatestAt", "最新结算时间", "datetime"],
      ["settlementIncomeCents", "收入合计", "money"],
      ["settlementExpenseCents", "支出合计", "money"],
      ["settlementNetCents", "结算净额", "money"],
    ],
  },
  {
    label: "平台资金",
    className: "wide-group-fund",
    columns: [
      ["fundCount", "资金数", "count"],
      ["fundScenes", "动账场景", "list"],
      ["fundLatestAt", "最新动账时间", "datetime"],
      ["fundNetCents", "资金净额", "money"],
      ["fundTransactionIds", "资金流水号", "list"],
    ],
  },
  {
    label: "成本",
    className: "wide-group-cost",
    columns: [
      ["costStatus", "成本状态", "text"],
      ["unitCostCents", "单位成本", "money"],
      ["totalCostCents", "订单成本", "money"],
    ],
  },
  {
    label: "追溯",
    className: "wide-group-source",
    columns: [["sourceRows", "来源Excel行", "sourceRows"]],
  },
];

const attentionResultStatuses = new Set([
  "missing_fund",
  "amount_mismatch",
  "multiple_candidates",
  "outside_auto_window",
  "not_calculable",
  "missing_historical_order",
  "missing_order_data",
  "multiple_history_orders",
  "settlement_receivable_mismatch",
  "settlement_receivable_not_calculable",
  "settlement_before_refund_review",
  "possibly_unsettled",
  "order_status_requires_review",
  "new_after_sale_status",
  "after_sale_refund_conflict",
  "refund_missing_after_sale",
  "missing_sku",
  "missing_cost",
  "multiple_cost_candidates",
  "waiting_classification",
]);

const elements = {
  primaryTabs: [...document.querySelectorAll(".primary-tab")],
  taskView: document.querySelector("#taskView"),
  importView: document.querySelector("#importView"),
  reconcileView: document.querySelector("#reconcileView"),
  reportView: document.querySelector("#reportView"),
  configView: document.querySelector("#configView"),
  taskContext: document.querySelector("#taskContext"),
  switchTaskButton: document.querySelector("#switchTaskButton"),
  form: document.querySelector("#taskForm"),
  formMessage: document.querySelector("#formMessage"),
  newTaskToggle: document.querySelector("#newTaskToggle"),
  newTaskDropdown: document.querySelector("#newTaskDropdown"),
  closeTaskDropdown: document.querySelector("#closeTaskDropdown"),
  taskMasterDataHint: document.querySelector("#taskMasterDataHint"),
  manageMasterDataButton: document.querySelector("#manageMasterDataButton"),
  taskLoading: document.querySelector("#taskLoading"),
  taskError: document.querySelector("#taskError"),
  taskEmpty: document.querySelector("#taskEmpty"),
  taskList: document.querySelector("#taskList"),
  refreshButton: document.querySelector("#refreshButton"),
  retryButton: document.querySelector("#retryButton"),
  loadSampleButton: document.querySelector("#loadSampleButton"),
  healthText: document.querySelector("#healthText"),
  ruleSummary: document.querySelector("#ruleSummary"),
  selectedTaskTitle: document.querySelector("#selectedTaskTitle"),
  selectedTaskMeta: document.querySelector("#selectedTaskMeta"),
  selectedTaskStatus: document.querySelector("#selectedTaskStatus"),
  taskLifecycleButton: document.querySelector("#taskLifecycleButton"),
  selectedTaskSample: document.querySelector("#selectedTaskSample"),
  uploadForm: document.querySelector("#uploadForm"),
  uploadMessage: document.querySelector("#uploadMessage"),
  platformBalanceForm: document.querySelector("#platformBalanceForm"),
  platformBalanceMessage: document.querySelector("#platformBalanceMessage"),
  platformBalanceImportSummary: document.querySelector("#platformBalanceImportSummary"),
  pendingSettlementForm: document.querySelector("#pendingSettlementForm"),
  pendingSettlementMessage: document.querySelector("#pendingSettlementMessage"),
  pendingSettlementImportSummary: document.querySelector("#pendingSettlementImportSummary"),
  detailLoading: document.querySelector("#detailLoading"),
  fileEmpty: document.querySelector("#fileEmpty"),
  fileResult: document.querySelector("#fileResult"),
  goToReconcileButton: document.querySelector("#goToReconcileButton"),
  reconcileEmpty: document.querySelector("#reconcileEmpty"),
  emptyGoToImportButton: document.querySelector("#emptyGoToImportButton"),
  reconcileContent: document.querySelector("#reconcileContent"),
  reconcileKpis: document.querySelector("#reconcileKpis"),
  recordTabs: document.querySelector("#recordTabs"),
  reconcileOverview: document.querySelector("#reconcileOverview"),
  reconciliationPane: document.querySelector("#reconciliationPane"),
  reconciliationBrowser: document.querySelector("#reconciliationBrowser"),
  recordPane: document.querySelector("#recordPane"),
  recordBrowser: document.querySelector("#recordBrowser"),
  operatingReportLoading: document.querySelector("#operatingReportLoading"),
  operatingReportError: document.querySelector("#operatingReportError"),
  operatingReportContent: document.querySelector("#operatingReportContent"),
  retryOperatingReportButton: document.querySelector("#retryOperatingReportButton"),
  configurationTabs: [...document.querySelectorAll(".configuration-tab")],
  templateConfigPanel: document.querySelector("#templateConfigPanel"),
  ruleConfigPanel: document.querySelector("#ruleConfigPanel"),
  baseDataConfigPanel: document.querySelector("#baseDataConfigPanel"),
  configurationLoading: document.querySelector("#configurationLoading"),
  configurationError: document.querySelector("#configurationError"),
  retryConfigurationButton: document.querySelector("#retryConfigurationButton"),
  templateConfigurationContent: document.querySelector("#templateConfigurationContent"),
  ruleConfigurationContent: document.querySelector("#ruleConfigurationContent"),
  baseDataConfigurationContent: document.querySelector("#baseDataConfigurationContent"),
};

const views = {
  tasks: elements.taskView,
  import: elements.importView,
  reconcile: elements.reconcileView,
  report: elements.reportView,
  config: elements.configView,
};

let activeView = "tasks";
let selectedTaskId = null;
let selectedTaskDetail = null;
let selectedFileId = null;
let selectedSheetName = null;
let selectedPageSize = 50;
let selectedReconciliationFilter = "all";
let selectedReconciliationPageSize = 50;
let selectedSupplementaryFilter = "all";
let selectedWideFilter = "all";
let selectedWideScene = "all";
let selectedWideQuery = "";
let selectedWidePageSize = 50;
let selectedPlatformBalanceFilter = "all";
let selectedPlatformBalancePageSize = 50;
let selectedPendingSettlementFilter = "all";
let selectedPendingSettlementPageSize = 50;
let operatingReportState = null;
let configurationState = null;
let masterDataState = null;

function setInitialMonth() {
  const monthInput = elements.form.elements.period;
  const now = new Date();
  monthInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

async function request(path, options = {}) {
  const requestHeaders = { ...(options.headers || {}) };
  if (typeof options.body === "string" && !requestHeaders["Content-Type"]) {
    requestHeaders["Content-Type"] = "application/json";
  }
  const response = await fetch(path, { ...options, headers: requestHeaders });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || "请求失败");
    error.payload = payload;
    throw error;
  }
  return payload;
}

function buildResultHeadingActions(result, pageSizeLabel) {
  const actions = document.createElement("div");
  actions.className = "table-controls result-heading-actions";
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "secondary-button compact-button export-button";
  exportButton.textContent = "导出当前筛选";
  exportButton.title = `导出当前筛选下全部${result.pagination.totalRows.toLocaleString("zh-CN")}笔，不受分页限制`;
  exportButton.addEventListener("click", () => downloadResultExport(result, exportButton));
  actions.append(exportButton, pageSizeLabel);
  return actions;
}

async function downloadResultExport(result, button) {
  const originalText = button.textContent;
  const originalTitle = button.title;
  button.disabled = true;
  button.textContent = "正在生成…";
  try {
    const query = new URLSearchParams({ status: result.filter });
    if (result.resultType === "wide_reconciliation") {
      query.set("scene", result.scene || "all");
      query.set("query", result.query || "");
    }
    const url = `/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(result.fileId)}/exports/${encodeURIComponent(result.resultType)}.xlsx?${query}`;
    const response = await fetch(url);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "导出失败");
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const fileName = encodedName ? decodeURIComponent(encodedName[1]) : "对账结果.xlsx";
    const objectUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = fileName;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    button.textContent = `已导出${result.pagination.totalRows.toLocaleString("zh-CN")}笔`;
    window.setTimeout(() => {
      button.textContent = originalText;
      button.title = originalTitle;
      button.disabled = false;
    }, 1800);
  } catch (error) {
    button.textContent = "导出失败";
    button.title = error.message;
    window.setTimeout(() => {
      button.textContent = originalText;
      button.title = originalTitle;
      button.disabled = false;
    }, 2200);
  }
}

function switchView(viewName, scrollToTop = true) {
  if (!["tasks", "config"].includes(viewName) && !selectedTaskId) return;
  if (viewName !== "tasks") setTaskDropdown(false);
  activeView = viewName;
  Object.entries(views).forEach(([name, view]) => {
    view.hidden = name !== viewName;
  });
  elements.taskContext.hidden = viewName === "tasks" || viewName === "config";
  elements.reconcileKpis.hidden = viewName !== "reconcile" || elements.reconcileContent.hidden;
  elements.primaryTabs.forEach((tab) => {
    const selected = tab.dataset.view === viewName;
    tab.classList.toggle("selected", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  // Configuration data can change during an import when previously unseen
  // platform values are collected. Always refresh on entry so the pending
  // mapping list never shows a stale pre-import snapshot.
  if (viewName === "config") loadConfiguration();
  if (viewName === "report") loadOperatingReport();
  if (scrollToTop) window.scrollTo({ top: 0, behavior: "smooth" });
}

function setTaskDropdown(open) {
  elements.newTaskDropdown.hidden = !open;
  elements.newTaskToggle.setAttribute("aria-expanded", String(open));
  if (open) {
    loadMasterDataOptions();
    window.requestAnimationFrame(() => elements.form.elements.entityId.focus());
  }
}

async function loadMasterDataOptions(force = false) {
  if (masterDataState && !force) {
    renderTaskMasterOptions();
    return;
  }
  try {
    masterDataState = await request("/api/master-data/options");
    renderTaskMasterOptions();
  } catch (error) {
    elements.form.elements.entityId.innerHTML = '<option value="">主体资料读取失败</option>';
    elements.form.elements.storeId.innerHTML = '<option value="">请到配置中心重试</option>';
    elements.form.elements.storeId.disabled = true;
  }
}

function renderTaskMasterOptions() {
  const entitySelect = elements.form.elements.entityId;
  const storeSelect = elements.form.elements.storeId;
  const previousEntity = entitySelect.value;
  const activeEntities = (masterDataState?.entities || []).filter((item) => item.status === "active");
  entitySelect.innerHTML = '<option value="">请选择企业主体</option>';
  activeEntities.forEach((entity) => {
    const option = document.createElement("option");
    option.value = entity.id;
    option.textContent = prototypeEntityName(entity.name);
    entitySelect.append(option);
  });
  if (activeEntities.some((item) => item.id === previousEntity)) entitySelect.value = previousEntity;
  if (!entitySelect.value && activeEntities.length === 1) entitySelect.value = activeEntities[0].id;
  renderTaskStoreOptions();
  const activeStoreCount = activeEntities.reduce(
    (count, entity) => count + entity.stores.filter((store) => store.status === "active").length,
    0
  );
  elements.taskMasterDataHint.classList.toggle("needs-setup", activeStoreCount === 0);
  elements.taskMasterDataHint.querySelector("span").textContent = activeStoreCount
    ? "主体和店铺来自配置中心，任务不会再产生同店异名。"
    : "还没有可用店铺，请先到配置中心建立主体和抖店店铺。";
}

function renderTaskStoreOptions() {
  const entityId = elements.form.elements.entityId.value;
  const storeSelect = elements.form.elements.storeId;
  const previousStore = storeSelect.value;
  const entity = (masterDataState?.entities || []).find((item) => item.id === entityId);
  const stores = (entity?.stores || []).filter((item) => item.status === "active");
  storeSelect.innerHTML = `<option value="">${entityId ? "请选择抖店店铺" : "请先选择企业主体"}</option>`;
  stores.forEach((store) => {
    const option = document.createElement("option");
    option.value = store.id;
    option.textContent = store.name;
    storeSelect.append(option);
  });
  if (stores.some((item) => item.id === previousStore)) storeSelect.value = previousStore;
  if (!storeSelect.value && stores.length === 1) storeSelect.value = stores[0].id;
  storeSelect.disabled = stores.length === 0;
}

function enableTaskViews() {
  elements.primaryTabs.forEach((tab) => {
    if (!["tasks", "config"].includes(tab.dataset.view)) tab.disabled = !selectedTaskId;
  });
}

function showConfigurationState(target) {
  elements.configurationLoading.hidden = target !== elements.configurationLoading;
  elements.configurationError.hidden = target !== elements.configurationError;
  elements.templateConfigurationContent.hidden = target !== elements.templateConfigurationContent;
}

function switchConfigurationPanel(panelName) {
  const panelMap = {
    template: elements.templateConfigPanel,
    rules: elements.ruleConfigPanel,
    "base-data": elements.baseDataConfigPanel,
  };
  Object.entries(panelMap).forEach(([name, panel]) => {
    panel.hidden = name !== panelName;
  });
  elements.configurationTabs.forEach((tab) => {
    tab.classList.toggle("selected", tab.dataset.configPanel === panelName);
  });
}

async function loadConfiguration() {
  showConfigurationState(elements.configurationLoading);
  try {
    configurationState = await request("/api/configuration");
    masterDataState = { entities: configurationState.masterData || [] };
    renderTaskMasterOptions();
    renderTemplateConfiguration(configurationState);
    renderRuleConfiguration(configurationState);
    renderBaseDataConfiguration(configurationState);
    showConfigurationState(elements.templateConfigurationContent);
  } catch (error) {
    elements.configurationError.querySelector("strong").textContent = error.message || "配置读取失败";
    showConfigurationState(elements.configurationError);
  }
}

function renderTemplateConfiguration(state) {
  const host = elements.templateConfigurationContent;
  const current = state.currentTemplate;
  const draft = state.draftTemplate;
  if (!current) {
    host.innerHTML = '<div class="state-box compact error"><strong>没有生效的账单模板</strong><span>系统已停止自动读取账单。</span></div>';
    return;
  }
  const testText = current.lastTestStatus === "passed"
    ? `已通过样例测试 · ${escapeHtml(current.lastTestFileName || "")}`
    : "未记录样例测试";
  const sheetSummary = current.sheets.map((sheet) => `
    <article class="template-sheet-summary">
      <strong>${escapeHtml(sheet.displayName)}</strong>
      <span>平台Sheet：${escapeHtml(sheet.sourceSheetName)}</span>
      <small>表头第${sheet.headerRow}行 · 数据从第${sheet.dataStartRow}行 · ${sheet.fields.filter((field) => field.required).length}个必要字段</small>
    </article>`).join("");
  host.innerHTML = `
    <section class="configuration-section">
      <div class="configuration-section-heading">
        <div>
          <span class="config-status current">正在生效</span>
          <h2>${escapeHtml(current.name)} ${escapeHtml(current.versionLabel)}</h2>
          <p>${testText}。新导入会记录使用的模板版本，历史文件不回写。</p>
        </div>
        ${draft ? '<span class="config-status draft">有未发布草稿</span>' : '<button class="primary-button compact-button" id="createTemplateDraftButton" type="button">复制为新版本</button>'}
      </div>
      <div class="template-sheet-summary-grid">${sheetSummary}</div>
    </section>
    <section class="configuration-section draft-section" id="templateDraftHost">
      ${draft ? buildTemplateDraftEditor(draft) : `
        <div class="configuration-empty">
          <strong>要调整Sheet名、表头位置或字段别名时，先复制一个草稿。</strong>
          <span>已发布版本不直接修改，避免已导入账单的口径被静默改变。</span>
        </div>`}
    </section>`;

  const createButton = host.querySelector("#createTemplateDraftButton");
  if (createButton) createButton.addEventListener("click", createTemplateDraft);
  if (draft) bindTemplateDraftEditor(draft);
}

function buildTemplateDraftEditor(draft) {
  const sheets = draft.sheets.map((sheet, index) => {
    const fields = sheet.fields.map((field) => `
      <tr class="template-field-row${field.required ? " required" : " optional-field"}" data-field-id="${escapeHtml(field.id)}">
        <td><strong>${escapeHtml(field.displayName)}</strong>${field.required ? '<span class="required-field-badge">必要</span>' : ""}</td>
        <td><input class="field-source-input" maxlength="120" value="${escapeHtml(field.sourceHeader)}" aria-label="${escapeHtml(field.displayName)}平台字段名" /></td>
        <td><input class="field-alias-input" maxlength="500" value="${escapeHtml(field.sourceAliases.join("，"))}" placeholder="用逗号分隔，可不填" aria-label="${escapeHtml(field.displayName)}别名" /></td>
      </tr>`).join("");
    return `
      <details class="template-sheet-editor" data-sheet-id="${escapeHtml(sheet.id)}"${index === 0 ? " open" : ""}>
        <summary>
          <span><strong>${escapeHtml(sheet.displayName)}</strong><small>平台Sheet ${escapeHtml(sheet.sourceSheetName)} · ${sheet.fields.length}个字段</small></span>
          <span>${sheet.fields.filter((field) => field.required).length}个必要字段</span>
        </summary>
        <div class="sheet-editor-body">
          <div class="sheet-editor-grid">
            <label>平台Sheet名<input class="sheet-source-input" maxlength="100" value="${escapeHtml(sheet.sourceSheetName)}" /></label>
            <label>Sheet别名<input class="sheet-alias-input" maxlength="500" value="${escapeHtml(sheet.sourceSheetAliases.join("，"))}" placeholder="例如：订单表，订单数据" /></label>
            <label>表头行<input class="sheet-header-row-input" type="number" min="1" max="1000" value="${sheet.headerRow}" /></label>
            <label>数据起始行<input class="sheet-data-row-input" type="number" min="2" max="1000000" value="${sheet.dataStartRow}" /></label>
          </div>
          <div class="field-table-heading">
            <div><strong>字段映射</strong><span>标准字段不变，只维护平台字段名和别名。</span></div>
            <button class="text-button toggle-optional-fields" type="button">显示全部字段</button>
          </div>
          <div class="template-field-table-wrap">
            <table class="template-field-table">
              <thead><tr><th>系统标准字段</th><th>平台字段名</th><th>可接受的别名</th></tr></thead>
              <tbody>${fields}</tbody>
            </table>
          </div>
        </div>
      </details>`;
  }).join("");
  const testStatus = draft.lastTestStatus === "passed"
    ? `<span class="template-test-result passed">样例测试通过 · ${escapeHtml(draft.lastTestFileName || "")}</span>`
    : draft.lastTestStatus === "failed"
      ? '<span class="template-test-result failed">样例测试未通过，请先修正映射</span>'
      : '<span class="template-test-result">修改并保存后，上传一份平台样例文件测试</span>';
  return `
    <form id="templateDraftForm" class="template-draft-form" novalidate>
      <div class="configuration-section-heading">
        <div><span class="config-status draft">草稿</span><h2>${escapeHtml(draft.name)} ${escapeHtml(draft.versionLabel)}</h2><p>修改不会影响当前生效版本。</p></div>
        <button class="secondary-button compact-button" type="submit">保存草稿</button>
      </div>
      <div class="template-meta-grid">
        <label>模板名称<input id="templateDraftName" maxlength="100" value="${escapeHtml(draft.name)}" /></label>
        <label>变更说明<input id="templateDraftNotes" maxlength="500" value="${escapeHtml(draft.notes || "")}" placeholder="例如：适配平台2026年8月新表头" /></label>
      </div>
      <div class="template-sheet-editor-list">${sheets}</div>
      <p class="form-message" id="templateDraftMessage" role="status" aria-live="polite"></p>
    </form>
    <div class="template-release-bar">
      <div>${testStatus}<small>每次修改草稿后，上一次测试结果自动失效。</small></div>
      <label class="secondary-button compact-button template-test-picker">选择样例测试<input id="templateTestFile" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" /></label>
      <button class="primary-button compact-button" id="activateTemplateButton" type="button"${draft.lastTestStatus === "passed" ? "" : " disabled"}>启用新版本</button>
    </div>
    <div id="templateTestDetail"></div>`;
}

function bindTemplateDraftEditor(draft) {
  const form = document.querySelector("#templateDraftForm");
  form.addEventListener("submit", (event) => saveTemplateDraft(event, draft));
  form.querySelectorAll(".toggle-optional-fields").forEach((button) => {
    button.addEventListener("click", () => {
      const editor = button.closest(".template-sheet-editor");
      const expanded = editor.classList.toggle("show-optional-fields");
      button.textContent = expanded ? "只看必要字段" : "显示全部字段";
    });
  });
  document.querySelector("#templateTestFile").addEventListener("change", (event) => testTemplateDraft(event, draft));
  document.querySelector("#activateTemplateButton").addEventListener("click", () => activateTemplateDraft(draft));
}

function parseAliasInput(value) {
  return value.split(/[,\uff0c\n]/).map((item) => item.trim()).filter(Boolean);
}

function collectTemplateDraftPayload() {
  const form = document.querySelector("#templateDraftForm");
  return {
    name: document.querySelector("#templateDraftName").value.trim(),
    notes: document.querySelector("#templateDraftNotes").value.trim() || null,
    sheets: [...form.querySelectorAll(".template-sheet-editor")].map((editor) => ({
      id: editor.dataset.sheetId,
      sourceSheetName: editor.querySelector(".sheet-source-input").value.trim(),
      sourceSheetAliases: parseAliasInput(editor.querySelector(".sheet-alias-input").value),
      headerRow: Number(editor.querySelector(".sheet-header-row-input").value),
      dataStartRow: Number(editor.querySelector(".sheet-data-row-input").value),
      fields: [...editor.querySelectorAll(".template-field-row")].map((row) => ({
        id: row.dataset.fieldId,
        sourceHeader: row.querySelector(".field-source-input").value.trim(),
        sourceAliases: parseAliasInput(row.querySelector(".field-alias-input").value),
      })),
    })),
  };
}

async function createTemplateDraft() {
  const button = document.querySelector("#createTemplateDraftButton");
  button.disabled = true;
  button.textContent = "正在复制……";
  try {
    await request("/api/configuration/templates/drafts", { method: "POST" });
    await loadConfiguration();
  } catch (error) {
    button.disabled = false;
    button.textContent = error.message;
  }
}

async function saveTemplateDraft(event, draft) {
  event.preventDefault();
  const message = document.querySelector("#templateDraftMessage");
  const button = event.currentTarget.querySelector("button[type='submit']");
  message.textContent = "";
  message.classList.remove("error");
  button.disabled = true;
  button.textContent = "正在保存……";
  try {
    await request(`/api/configuration/templates/${encodeURIComponent(draft.id)}`, {
      method: "POST",
      body: JSON.stringify(collectTemplateDraftPayload()),
    });
    await loadConfiguration();
    const nextMessage = document.querySelector("#templateDraftMessage");
    if (nextMessage) nextMessage.textContent = "草稿已保存，请重新上传样例测试。";
  } catch (error) {
    message.classList.add("error");
    message.textContent = error.message;
    button.disabled = false;
    button.textContent = "保存草稿";
  }
}

async function testTemplateDraft(event, draft) {
  const input = event.currentTarget;
  const file = input.files[0];
  if (!file) return;
  const detail = document.querySelector("#templateTestDetail");
  detail.innerHTML = '<div class="state-box compact">正在用样例检查Sheet和字段映射……</div>';
  try {
    const result = await request(`/api/configuration/templates/${encodeURIComponent(draft.id)}/test`, {
      method: "POST",
      headers: { "X-File-Name": encodeURIComponent(file.name) },
      body: file,
    });
    const inspection = result.inspection;
    if (inspection.status === "passed") {
      detail.innerHTML = `<div class="state-box compact success"><strong>测试通过</strong><span>识别${inspection.foundRequiredSheetCount}/${inspection.requiredSheetCount}张必要表，可以启用新版本。</span></div>`;
    } else {
      detail.innerHTML = `<div class="state-box compact error"><strong>测试未通过</strong><span>${inspection.errors.map(escapeHtml).join("；")}</span></div>`;
    }
    await loadConfiguration();
  } catch (error) {
    detail.innerHTML = `<div class="state-box compact error"><strong>测试失败</strong><span>${escapeHtml(error.message)}</span></div>`;
  } finally {
    input.value = "";
  }
}

async function activateTemplateDraft(draft) {
  if (!window.confirm(`确认启用${draft.versionLabel}？\n\n只影响此后新导入的文件，历史文件保留原模板版本。`)) return;
  const button = document.querySelector("#activateTemplateButton");
  button.disabled = true;
  button.textContent = "正在启用……";
  try {
    await request(`/api/configuration/templates/${encodeURIComponent(draft.id)}/activate`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    });
    await loadConfiguration();
  } catch (error) {
    button.disabled = false;
    button.textContent = error.message;
  }
}

function renderRuleConfiguration(state) {
  const rule = state.currentRule;
  const draft = state.draftRule;
  const activeCount = state.rules.filter((item) => item.status === "active").length;
  const trialCount = state.rules.filter((item) => item.status === "trial").length;
  elements.ruleConfigurationContent.innerHTML = `
    <section class="configuration-section">
      <div class="configuration-section-heading">
        <div><span class="config-status current">正在生效</span><h2>对账规则 ${escapeHtml(rule.versionLabel)}</h2><p>新规则只用于之后新建的任务，已有任务继续使用原规则版本。</p></div>
        ${draft ? '<span class="config-status draft">有未发布草稿</span>' : '<button class="primary-button compact-button" id="createRuleDraftButton" type="button">复制为新版本</button>'}
      </div>
      <div class="rule-parameter-grid">
        <article><span>金额容差</span><strong>${(rule.toleranceCents / 100).toFixed(2)}元</strong></article>
        <article><span>退款自动归组</span><strong>${Math.round(rule.refundAutoGroupSeconds / 60)}分钟</strong></article>
        <article><span>退款候选范围</span><strong>${Math.round(rule.refundCandidateSeconds / 3600)}小时</strong></article>
        <article><span>默认等待结算</span><strong>${rule.settlementWaitDays}天</strong></article>
      </div>
      <div class="rule-version-note"><strong>当前发布策略</strong><span>已发布版本不直接修改；金额使用分保存，时间窗口使用秒保存。</span></div>
    </section>
    ${draft ? buildRuleDraftEditor(draft) : ""}
    <section class="configuration-section">
      <div class="configuration-section-heading rule-catalog-heading">
        <div><span class="config-status inventory">规则清单</span><h2>R01—R13</h2><p>参数可配置，公式、匹配主键和证据条件仍由固定规则保护。</p></div>
        <div class="configuration-counts"><strong>${activeCount}条正式</strong><span>${trialCount}条试运行</span></div>
      </div>
      <div class="rule-catalog-list">${state.rules.map((item) => `
        <article class="rule-catalog-row">
          <b>${escapeHtml(item.code)}</b>
          <div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.summary)}</span></div>
          <span>${escapeHtml(item.category)}</span>
          <em class="${item.status}">${item.status === "active" ? "正式" : "试运行"}</em>
          <small>${escapeHtml(item.source)}</small>
        </article>`).join("")}</div>
      <div class="configuration-boundary-note"><strong>当前边界</strong><span>本期只开放4个有边界的参数，不允许自定义公式、删除硬校验或绕过证据唯一性。</span></div>
    </section>`;

  const createButton = elements.ruleConfigurationContent.querySelector("#createRuleDraftButton");
  if (createButton) createButton.addEventListener("click", createRuleDraft);
  if (draft) bindRuleDraftEditor(draft);
}

function buildRuleDraftEditor(draft) {
  const testSummary = draft.fixedCases;
  const testStatus = draft.lastTestStatus === "passed"
    ? `<span class="template-test-result passed">23个固定案例全部通过</span>`
    : draft.lastTestStatus === "failed"
      ? `<span class="template-test-result failed">固定案例未全部通过</span>`
      : '<span class="template-test-result">修改并保存后，需重新试算23个固定案例</span>';
  return `
    <section class="configuration-section draft-section">
      <form id="ruleDraftForm" class="rule-draft-form" novalidate>
        <div class="configuration-section-heading">
          <div><span class="config-status draft">草稿</span><h2>对账规则 ${escapeHtml(draft.versionLabel)}</h2><p>修改不会影响当前生效版本。</p></div>
          <button class="secondary-button compact-button" type="submit">保存草稿</button>
        </div>
        <div class="rule-draft-grid">
          <label><span>金额容差（元）</span><input id="ruleToleranceYuan" type="number" min="0" max="1" step="0.01" value="${(draft.toleranceCents / 100).toFixed(2)}" /><small>0—1.00元；仅处理尾差，不用于吸收业务差异</small></label>
          <label><span>退款自动归组（分钟）</span><input id="ruleAutoGroupMinutes" type="number" min="1" max="60" step="1" value="${Math.round(draft.refundAutoGroupSeconds / 60)}" /><small>1—60分钟；仍必须同子订单、同业务且组合唯一</small></label>
          <label><span>退款候选范围（小时）</span><input id="ruleCandidateHours" type="number" min="2" max="72" step="1" value="${Math.round(draft.refundCandidateSeconds / 3600)}" /><small>2—72小时；必须大于自动归组窗口</small></label>
          <label><span>结算等待（天）</span><input id="ruleSettlementWaitDays" type="number" min="1" max="90" step="1" value="${draft.settlementWaitDays}" /><small>1—90天；取得平台预计结算日时优先用平台日期</small></label>
        </div>
        <label class="rule-change-notes"><span>变更说明（发布必填）</span><textarea id="ruleDraftNotes" maxlength="500" placeholder="例如：根据店铺近三月结算时效，将默认等待从7天调整为10天">${escapeHtml(draft.notes || "")}</textarea></label>
        <p class="form-message" id="ruleDraftMessage" role="status" aria-live="polite"></p>
      </form>
      <div class="template-release-bar rule-release-bar">
        <div>${testStatus}<small>每次修改参数后，上一次试算结果自动失效。</small></div>
        <button class="secondary-button compact-button" id="testRuleDraftButton" type="button">保存并试算23个案例</button>
        <button class="primary-button compact-button" id="activateRuleDraftButton" type="button"${draft.lastTestStatus === "passed" ? "" : " disabled"}>启用新规则</button>
      </div>
      ${buildFixedCaseSummary(testSummary)}
    </section>`;
}

function buildFixedCaseSummary(result) {
  if (!result) return "";
  return `
    <div class="fixed-case-summary ${result.status}">
      <div><strong>${result.passedCount}/${result.totalCount}通过</strong><span>耗时${result.durationSeconds}秒 · 失败${result.failedCount}项</span></div>
      <div class="fixed-case-grid">${result.caseResults.map((item) => `
        <span class="fixed-case-item ${item.status}" title="${escapeHtml(item.message || item.label)}"><b>${escapeHtml(item.caseId)}</b>${escapeHtml(item.label)}</span>`).join("")}</div>
    </div>`;
}

function bindRuleDraftEditor(draft) {
  document.querySelector("#ruleDraftForm").addEventListener("submit", (event) => saveRuleDraft(event, draft));
  document.querySelector("#testRuleDraftButton").addEventListener("click", () => testRuleDraft(draft));
  document.querySelector("#activateRuleDraftButton").addEventListener("click", () => activateRuleDraft(draft));
}

function collectRuleDraftPayload() {
  const toleranceYuan = Number(document.querySelector("#ruleToleranceYuan").value);
  const autoMinutes = Number(document.querySelector("#ruleAutoGroupMinutes").value);
  const candidateHours = Number(document.querySelector("#ruleCandidateHours").value);
  const waitDays = Number(document.querySelector("#ruleSettlementWaitDays").value);
  if (![toleranceYuan, autoMinutes, candidateHours, waitDays].every(Number.isFinite)) {
    throw new Error("请完整填写四个规则参数");
  }
  return {
    toleranceCents: Math.round(toleranceYuan * 100),
    refundAutoGroupSeconds: Math.round(autoMinutes * 60),
    refundCandidateSeconds: Math.round(candidateHours * 3600),
    settlementWaitDays: Math.round(waitDays),
    notes: document.querySelector("#ruleDraftNotes").value.trim(),
  };
}

async function createRuleDraft() {
  const button = document.querySelector("#createRuleDraftButton");
  button.disabled = true;
  button.textContent = "正在复制……";
  try {
    await request("/api/configuration/rules/drafts", { method: "POST" });
    await loadConfiguration();
  } catch (error) {
    button.disabled = false;
    button.textContent = error.message;
  }
}

async function saveRuleDraft(event, draft) {
  event.preventDefault();
  const message = document.querySelector("#ruleDraftMessage");
  try {
    const payload = collectRuleDraftPayload();
    await request(`/api/configuration/rules/${encodeURIComponent(draft.id)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await loadConfiguration();
    const nextMessage = document.querySelector("#ruleDraftMessage");
    if (nextMessage) nextMessage.textContent = "草稿已保存，请重新试算固定案例。";
  } catch (error) {
    message.textContent = error.message;
    message.classList.add("error");
  }
}

async function testRuleDraft(draft) {
  const button = document.querySelector("#testRuleDraftButton");
  const message = document.querySelector("#ruleDraftMessage");
  button.disabled = true;
  button.textContent = "正在试算……";
  try {
    const payload = collectRuleDraftPayload();
    await request(`/api/configuration/rules/${encodeURIComponent(draft.id)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await request(`/api/configuration/rules/${encodeURIComponent(draft.id)}/test`, { method: "POST" });
    await loadConfiguration();
  } catch (error) {
    button.disabled = false;
    button.textContent = "保存并试算23个案例";
    message.textContent = error.message;
    message.classList.add("error");
  }
}

async function activateRuleDraft(draft) {
  if (!window.confirm(`确认启用${draft.versionLabel}？\n\n只影响之后新建的任务，已有任务保留原规则版本。`)) return;
  const button = document.querySelector("#activateRuleDraftButton");
  button.disabled = true;
  button.textContent = "正在启用……";
  try {
    await request(`/api/configuration/rules/${encodeURIComponent(draft.id)}/activate`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    });
    await Promise.all([loadConfiguration(), loadHealthAndRule(), loadTasks(false)]);
  } catch (error) {
    button.disabled = false;
    button.textContent = error.message;
  }
}

function renderBaseDataConfiguration(state) {
  const entities = state.masterData || [];
  const activeEntities = entities.filter((item) => item.status === "active");
  const stores = entities.flatMap((entity) => entity.stores.map((store) => ({ ...store, entity })));
  const pending = state.unmappedValues || [];
  const currentMappings = (state.valueMappings || []).filter((item) => item.isCurrent);
  const entityOptions = activeEntities.map(
    (item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(prototypeEntityName(item.name))}</option>`
  ).join("");
  const entityRows = entities.length ? entities.map((entity) => `
    <article class="master-entity-card">
      <div class="master-entity-heading">
        <div><strong>${escapeHtml(prototypeEntityName(entity.name))}</strong><span>${entity.stores.length}个抖店店铺</span></div>
        <span class="config-status ${entity.status === "active" ? "current" : "inactive"}">${entity.status === "active" ? "使用中" : "已停用"}</span>
      </div>
      <div class="master-store-list">${entity.stores.length ? entity.stores.map((store) => `
        <div class="master-store-row">
          <div><b>${escapeHtml(store.name)}</b><span>${escapeHtml(store.platformCode)} · ${store.taskCount}个任务</span></div>
          <button type="button" class="text-button store-status-button" data-store-id="${escapeHtml(store.id)}" data-next-status="${store.status === "active" ? "inactive" : "active"}">${store.status === "active" ? "停用" : "重新启用"}</button>
        </div>`).join("") : '<div class="empty-inline">还没有店铺，请在右侧添加。</div>'}</div>
    </article>`).join("") : '<div class="state-box compact"><strong>还没有主体和店铺</strong><span>先建立企业主体，再添加抖店店铺；新建任务将直接从下拉框选择。</span></div>';
  const pendingRows = pending.length ? pending.map((item) => `
    <article class="unmapped-value-card">
      <div><span class="config-status warning">待映射</span><strong>${escapeHtml(item.sourceValue)}</strong></div>
      <p>${escapeHtml(item.mappingTypeName)} · 累计${Number(item.occurrenceCount || 0).toLocaleString("zh-CN")}行 · 最近来自${escapeHtml(prototypeEntityName(item.entityName || "未知主体"))}/${escapeHtml(item.storeName || "未知店铺")}</p>
      <button type="button" class="secondary-button compact-button map-pending-button" data-mapping-type="${escapeHtml(item.mappingType)}" data-source-value="${escapeHtml(item.sourceValue)}">处理这个值</button>
    </article>`).join("") : '<div class="state-box compact success"><strong>没有待映射平台值</strong><span>以后导入出现新售后状态或新资金场景，会自动出现在这里并停止自动判断。</span></div>';
  const mappingRows = currentMappings.map((item) => `
    <tr><td>${escapeHtml(item.mappingTypeName)}</td><td>${escapeHtml(item.sourceValue)}</td><td>${escapeHtml(item.standardName)}</td><td>${escapeHtml(item.versionLabel)}</td><td>${escapeHtml(item.effectiveFrom)}</td><td title="${escapeHtml(item.notes)}">${escapeHtml(item.notes)}</td></tr>`
  ).join("");
  elements.baseDataConfigurationContent.innerHTML = `
    <section class="configuration-section">
      <div class="configuration-section-heading">
        <div><span class="config-status current">可以维护</span><h2>主体与店铺</h2><p>任务只选择已维护店铺；停用不会删除历史任务，也不会改写原主体和店铺名称。</p></div>
        <span class="config-status current">${activeEntities.length}个主体 · ${stores.filter((item) => item.status === "active").length}个在用店铺</span>
      </div>
      <div class="master-data-layout">
        <div class="master-entity-list">${entityRows}</div>
        <div class="master-data-forms">
          <form id="addEntityForm" class="compact-config-form">
            <strong>新增企业主体</strong>
            <label>主体名称<input name="name" maxlength="100" placeholder="例如：星禾商贸" required /></label>
            <button class="secondary-button" type="submit">保存主体</button>
          </form>
          <form id="addStoreForm" class="compact-config-form">
            <strong>新增抖店店铺</strong>
            <label>所属主体<select name="entityId" required><option value="">请选择主体</option>${entityOptions}</select></label>
            <label>店铺名称<input name="name" maxlength="100" placeholder="例如：抖店华东店" required /></label>
            <button class="secondary-button" type="submit" ${activeEntities.length ? "" : "disabled"}>保存店铺</button>
          </form>
        </div>
      </div>
    </section>
    <section class="configuration-section mapping-section">
      <div class="configuration-section-heading">
        <div><span class="config-status ${pending.length ? "warning" : "current"}">${pending.length}个待处理</span><h2>平台值映射</h2><p>原Excel值始终保留；映射只影响生效日期后的新导入，已有文件和结果不重算。</p></div>
        <span class="config-status inventory">${currentMappings.length}条当前映射</span>
      </div>
      <div class="unmapped-value-grid">${pendingRows}</div>
      <form id="valueMappingForm" class="value-mapping-form">
        <div><strong>新增或修订映射</strong><span>同一平台原值再次保存会生成V2、V3，不覆盖旧版本。</span></div>
        <label>类型<select name="mappingType" required>${(state.mappingTypes || []).map((item) => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.name)}</option>`).join("")}</select></label>
        <label>平台原值<input name="sourceValue" maxlength="200" required placeholder="从待映射清单带入，或手工填写平台新值" /></label>
        <label>标准值<select name="standardCode" required></select></label>
        <label>生效日期<input name="effectiveFrom" type="date" value="${escapeHtml(localToday())}" required /></label>
        <label class="mapping-notes">映射说明<input name="notes" maxlength="500" required placeholder="例如：根据平台最新账单样例确认，作为货款结算入账" /></label>
        <button class="primary-button" type="submit">保存并启用映射</button>
        <p class="form-message" role="status"></p>
      </form>
      <div class="mapping-history-table"><table><thead><tr><th>类型</th><th>平台原值</th><th>当前标准值</th><th>版本</th><th>生效日期</th><th>说明</th></tr></thead><tbody>${mappingRows}</tbody></table></div>
      <div class="config-boundary-note"><strong>当前边界</strong><span>这里只维护售后状态和资金场景；商品历史成本、生效税率、会计科目和凭证规则未取得真实资料前不开放。</span></div>
    </section>`;
  bindBaseDataConfiguration(state);
}

function localToday() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function populateMappingStandards(state, selectedCode = "") {
  const form = document.querySelector("#valueMappingForm");
  if (!form) return;
  const mappingType = form.elements.mappingType.value;
  const definition = (state.mappingTypes || []).find((item) => item.code === mappingType);
  form.elements.standardCode.innerHTML = "";
  (definition?.standards || []).forEach((standard) => {
    const option = document.createElement("option");
    option.value = standard.code;
    option.textContent = `${standard.name}（${standard.canonicalValue}）`;
    option.selected = standard.code === selectedCode;
    form.elements.standardCode.append(option);
  });
}

function bindBaseDataConfiguration(state) {
  const entityForm = document.querySelector("#addEntityForm");
  const storeForm = document.querySelector("#addStoreForm");
  const mappingForm = document.querySelector("#valueMappingForm");
  entityForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = entityForm.querySelector("button[type='submit']");
    button.disabled = true;
    try {
      await request("/api/configuration/entities", { method: "POST", body: JSON.stringify({ name: entityForm.elements.name.value }) });
      await loadConfiguration();
    } catch (error) {
      window.alert(error.message);
      button.disabled = false;
    }
  });
  storeForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = storeForm.querySelector("button[type='submit']");
    button.disabled = true;
    try {
      await request("/api/configuration/stores", { method: "POST", body: JSON.stringify({ entityId: storeForm.elements.entityId.value, name: storeForm.elements.name.value }) });
      await loadConfiguration();
    } catch (error) {
      window.alert(error.message);
      button.disabled = false;
    }
  });
  document.querySelectorAll(".store-status-button").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await request(`/api/configuration/stores/${encodeURIComponent(button.dataset.storeId)}/status`, { method: "POST", body: JSON.stringify({ status: button.dataset.nextStatus }) });
        await loadConfiguration();
      } catch (error) {
        window.alert(error.message);
        button.disabled = false;
      }
    });
  });
  if (mappingForm) {
    populateMappingStandards(state);
    mappingForm.elements.mappingType.addEventListener("change", () => populateMappingStandards(state));
    mappingForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = mappingForm.querySelector("button[type='submit']");
      const message = mappingForm.querySelector(".form-message");
      button.disabled = true;
      message.textContent = "正在保存版本……";
      message.classList.remove("error");
      try {
        const payload = Object.fromEntries(new FormData(mappingForm).entries());
        await request("/api/configuration/value-mappings", { method: "POST", body: JSON.stringify(payload) });
        await loadConfiguration();
      } catch (error) {
        message.textContent = error.message;
        message.classList.add("error");
        button.disabled = false;
      }
    });
  }
  document.querySelectorAll(".map-pending-button").forEach((button) => {
    button.addEventListener("click", () => {
      const form = document.querySelector("#valueMappingForm");
      form.elements.mappingType.value = button.dataset.mappingType;
      populateMappingStandards(state);
      form.elements.sourceValue.value = button.dataset.sourceValue;
      form.elements.notes.value = "根据平台账单原值确认标准含义";
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      form.elements.standardCode.focus();
    });
  });
}

async function loadHealthAndRule() {
  try {
    const [health, settings] = await Promise.all([
      request("/api/health"),
      request("/api/settings"),
    ]);
    elements.healthText.textContent = `服务正常 · v${health.version}`;
    const rule = settings.currentRule;
    elements.ruleSummary.innerHTML = "";
    const title = document.createElement("strong");
    title.textContent = `当前规则 ${rule.versionLabel}`;
    const detail = document.createElement("span");
    detail.textContent = `金额差额 ${(rule.toleranceCents / 100).toFixed(2)}元 · 退款归组 ${Math.round(rule.refundAutoGroupSeconds / 60)}分钟 · 默认等待 ${rule.settlementWaitDays}天`;
    elements.ruleSummary.append(title, detail);
  } catch (error) {
    elements.healthText.textContent = "服务检查失败";
    elements.ruleSummary.textContent = "规则读取失败，请重新启动应用。";
  }
}

function showTaskState(target) {
  [elements.taskLoading, elements.taskError, elements.taskEmpty, elements.taskList].forEach((element) => {
    element.hidden = element !== target;
  });
}

function renderTasks(tasks) {
  if (!tasks.length) {
    showTaskState(elements.taskEmpty);
    return;
  }
  elements.taskList.innerHTML = "";
  for (const task of tasks) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "task-card";
    card.dataset.taskId = task.id;
    card.classList.toggle("selected", task.id === selectedTaskId);
    card.addEventListener("click", () => selectTask(task.id, "auto"));

    const period = document.createElement("div");
    period.className = "task-period";
    const month = document.createElement("strong");
    month.textContent = task.period;
    const platform = document.createElement("span");
    platform.textContent = "DOUYIN";
    period.append(month, platform);

    const info = document.createElement("div");
    info.className = "task-info";
    const title = document.createElement("h3");
    title.textContent = task.storeName;
    if (task.isSample) {
      const sample = document.createElement("span");
      sample.className = "sample-badge inline";
      sample.textContent = "样例";
      title.append(" ", sample);
    }
    const meta = document.createElement("p");
    meta.textContent = `${prototypeEntityName(task.entityName)} · 规则 ${task.ruleVersionLabel}`;
    info.append(title, meta);

    const action = document.createElement("div");
    action.className = "task-action";
    const status = document.createElement("span");
    status.className = `task-status ${task.status}`;
    status.textContent = statusLabels[task.status] || task.status;
    const next = document.createElement("small");
    next.textContent = task.status === "draft" ? "去导入 →" : "查看对账 →";
    action.append(status, next);
    card.append(period, info, action);
    elements.taskList.append(card);
  }
  showTaskState(elements.taskList);
}

async function loadTasks(refreshSelected = true) {
  showTaskState(elements.taskLoading);
  try {
    const payload = await request("/api/tasks");
    renderTasks(payload.tasks);
    if (refreshSelected && selectedTaskId && payload.tasks.some((task) => task.id === selectedTaskId)) {
      await loadTaskDetail(selectedTaskId, null);
    }
  } catch (error) {
    showTaskState(elements.taskError);
  }
}

async function submitTask(event) {
  event.preventDefault();
  elements.formMessage.textContent = "";
  elements.formMessage.classList.remove("error");
  const submitButton = elements.form.querySelector("button[type='submit']");
  submitButton.disabled = true;
  submitButton.textContent = "正在建立……";
  const payload = Object.fromEntries(new FormData(elements.form).entries());
  try {
    const result = await request("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
    elements.formMessage.textContent = "月度任务已建立。";
    setTaskDropdown(false);
    await loadTasks(false);
    await selectTask(result.task.id, "import");
  } catch (error) {
    elements.formMessage.classList.add("error");
    if (error.payload && error.payload.existingTask) {
      elements.formMessage.textContent = "该店铺和月份已有任务，已打开原任务。";
      await loadTasks(false);
      await selectTask(error.payload.existingTask.id, "auto");
    } else {
      elements.formMessage.textContent = error.message;
    }
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "建立月度任务";
  }
}

async function selectTask(taskId, targetView = "auto") {
  selectedTaskId = taskId;
  operatingReportState = null;
  selectedSheetName = null;
  selectedReconciliationFilter = "all";
  selectedSupplementaryFilter = "all";
  selectedPendingSettlementFilter = "all";
  enableTaskViews();
  document.querySelectorAll(".task-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.taskId === taskId);
  });
  await loadTaskDetail(taskId, targetView);
}

async function loadTaskDetail(taskId, targetView) {
  setImportDetailState(elements.detailLoading);
  elements.uploadMessage.textContent = "";
  elements.uploadMessage.classList.remove("error");
  elements.platformBalanceMessage.textContent = "";
  elements.platformBalanceMessage.classList.remove("error");
  elements.pendingSettlementMessage.textContent = "";
  elements.pendingSettlementMessage.classList.remove("error");
  try {
    const detail = await request(`/api/tasks/${encodeURIComponent(taskId)}`);
    selectedTaskDetail = detail;
    renderTaskContext(detail.task, detail.files.length, detail.completion);
    renderImportPage(detail.files);
    renderPlatformBalanceImport(detail.platformBalance);
    renderPendingSettlementImport(detail.pendingSettlement);
    renderReconciliationPage(detail.files);
    if (targetView) {
      const nextView = targetView === "auto"
        ? (detail.files[0] && detail.files[0].dataImport ? "reconcile" : "import")
        : targetView;
      switchView(nextView);
    }
  } catch (error) {
    elements.selectedTaskTitle.textContent = "任务读取失败";
    elements.selectedTaskMeta.textContent = error.message;
    setImportDetailState(elements.fileEmpty);
  }
}

function renderTaskContext(task, versionCount, completion) {
  elements.selectedTaskTitle.textContent = `${task.period} · ${task.storeName}`;
  elements.selectedTaskMeta.textContent = `${prototypeEntityName(task.entityName)} · 抖店 · 规则 ${task.ruleVersionLabel} · ${versionCount}个文件版本`;
  elements.selectedTaskStatus.textContent = statusLabels[task.status] || task.status;
  elements.selectedTaskStatus.className = `task-status ${task.status}`;
  elements.selectedTaskSample.hidden = !task.isSample;
  const hasProcessedFile = Boolean(completion && completion.latestFileId);
  elements.taskLifecycleButton.hidden = !hasProcessedFile;
  elements.taskLifecycleButton.textContent = task.status === "completed" ? "重新打开" : "完成本期";
  elements.taskLifecycleButton.classList.toggle("reopen", task.status === "completed");
  setTaskReadOnly(task.status === "completed");
}

function showOperatingReportState(target) {
  [
    elements.operatingReportLoading,
    elements.operatingReportError,
    elements.operatingReportContent,
  ].forEach((element) => {
    element.hidden = element !== target;
  });
}

async function loadOperatingReport() {
  if (!selectedTaskId) return;
  showOperatingReportState(elements.operatingReportLoading);
  try {
    operatingReportState = await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/operating-report-readiness`
    );
    renderOperatingReport(operatingReportState);
    showOperatingReportState(elements.operatingReportContent);
  } catch (error) {
    elements.operatingReportError.querySelector("strong").textContent = error.message || "经营报表读取失败";
    showOperatingReportState(elements.operatingReportError);
  }
}

function renderOperatingReport(report) {
  if (report.status === "no_import") {
    elements.operatingReportContent.innerHTML = `
      <article class="card report-empty-state">
        <span class="report-empty-icon">表</span>
        <strong>导入账单后，才会生成本次经营分析</strong>
        <p>${escapeHtml(report.scopeNotice)}</p>
        <button class="primary-button inline-button" type="button" data-report-action="import">去导入数据</button>
      </article>`;
    bindOperatingReportActions();
    return;
  }

  const summary = report.summary || {};
  const completeness = report.completeness || {};
  const source = report.source || {};
  const lines = report.statement?.lines || [];
  const evidence = report.evidence || [];
  const blockers = completeness.blockingItems || [];
  const reports = report.reports || [];
  const operatingEvidence = report.operatingEvidence || {};
  const evidenceCategories = operatingEvidence.categories || [];
  const profitTrial = report.profitTrial || null;
  const reportReadOnly = selectedTaskDetail?.task?.status === "completed";
  elements.operatingReportContent.innerHTML = `
    <article class="report-workspace">
      <header class="report-compact-header">
        <div>
          <div class="report-title-row">
            <span class="step-label">经营报表准备度</span>
            <span class="report-scope-badge">${escapeHtml(report.reportTypeLabel)}</span>
          </div>
          <h2>${profitTrial ? "已打通店铺利润模拟试算" : "先看现在哪些金额可信，再决定能否出利润"}</h2>
          <p>${escapeHtml(source.originalName || "当前任务")} · ${Number(source.totalRecordCount || 0).toLocaleString("zh-CN")}行源数据</p>
        </div>
        <span class="report-readiness-status">${escapeHtml(report.statusLabel)}</span>
      </header>

      <section class="report-summary-strip" aria-label="当前可确认金额">
        <div><span>平台结算净额</span><strong>${formatOptionalMoney(summary.settlementNetCents)}</strong><small>不是利润</small></div>
        <div><span>退款成功</span><strong>${formatOptionalMoney(summary.successfulRefundCents)}</strong><small>${Number(summary.successfulRefundCount || 0).toLocaleString("zh-CN")}笔最终状态</small></div>
        <div><span>${profitTrial ? "模拟经营利润" : "静态成本试算"}</span><strong>${formatOptionalMoney(profitTrial?.amountCents ?? summary.staticCostCents)}</strong><small>${profitTrial ? "造数试算，非正式报表" : `${Number(summary.staticCostOrderCount || 0).toLocaleString("zh-CN")}笔订单，未进入利润`}</small></div>
        <div><span>资料准备</span><strong>${Number(completeness.availableItemCount || 0)}/${Number(completeness.totalItemCount || 0)}项</strong><small>另有${Number(completeness.partialItemCount || 0)}项部分可用</small></div>
      </section>

      <div class="report-guardrail">
        <strong>${profitTrial ? "当前只出模拟试算" : "当前不出“店铺利润”"}</strong>
        <span>${escapeHtml(report.scopeNotice)}</span>
      </div>

      ${profitTrial ? `
        <section class="report-panel profit-trial-panel">
          <div class="profit-trial-heading">
            <div><span class="step-label">造数验证</span><h3>${escapeHtml(profitTrial.title)}</h3><p>${escapeHtml(profitTrial.formula)}</p></div>
            <div class="profit-trial-total"><span>模拟经营利润</span><strong>${formatOptionalMoney(profitTrial.amountCents)}</strong><small>${escapeHtml(profitTrial.statusLabel)}</small></div>
          </div>
          <div class="profit-trial-lines">${(profitTrial.lines || []).map((line) => `
            <div class="${line.code === "trial_operating_profit" ? "total" : ""}">
              <span>${escapeHtml(line.label)}</span>
              <strong class="${Number(line.effectCents || 0) < 0 ? "negative" : ""}">${formatOptionalMoney(line.effectCents)}</strong>
              <small>${escapeHtml(line.source)}</small>
            </div>`).join("")}</div>
          <div class="profit-trial-notice"><strong>边界</strong><span>${escapeHtml(profitTrial.notice)}</span></div>
        </section>` : ""}

      <section class="report-panel report-statement-panel">
        <div class="report-section-heading">
          <div><span class="step-label">金额表</span><h3>${escapeHtml(report.statement?.title || "当前可确认金额")}</h3></div>
          <span>每一行都标明来源和使用边界</span>
        </div>
        <div class="report-table-scroll">
          <table class="report-table">
            <thead><tr><th>项目</th><th>金额</th><th>状态</th><th>数据来源</th><th>说明</th></tr></thead>
            <tbody>${lines.map((line) => `
              <tr>
                <td><strong>${escapeHtml(line.label)}</strong></td>
                <td class="report-money">${formatOptionalMoney(line.amountCents)}</td>
                <td><span class="report-item-status status-${escapeHtml(line.status)}">${escapeHtml(line.statusLabel)}</span></td>
                <td>${escapeHtml(line.sourceLabel)}</td>
                <td>${escapeHtml(line.note)}</td>
              </tr>`).join("")}</tbody>
          </table>
        </div>
      </section>

      <div class="report-detail-grid">
        <section class="report-panel">
          <div class="report-section-heading">
            <div><span class="step-label">资料检查</span><h3>利润所需数据</h3></div>
          </div>
          <div class="report-evidence-list">${evidence.map((item) => `
            <div class="report-evidence-item">
              <span class="report-item-status status-${escapeHtml(item.status)}">${escapeHtml(item.statusLabel)}</span>
              <div><strong>${escapeHtml(item.label)}</strong><p>${escapeHtml(item.note)}</p></div>
            </div>`).join("")}</div>
        </section>

        <section class="report-panel">
          <div class="report-section-heading">
            <div><span class="step-label">解锁路径</span><h3>下一份资料解锁什么</h3></div>
          </div>
          <div class="report-blocker-list">${blockers.map((item) => `
            <div><b>${escapeHtml(item.taskId)}</b><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.fileName || item.unlock)}</small></span><em class="${item.status === "trial_passed" ? "passed" : item.status === "received_pending_mapping" ? "received" : ""}">${escapeHtml(item.statusLabel || "Pending")}</em></div>`).join("")}</div>
        </section>
      </div>

      <section class="report-panel operating-evidence-panel">
        <div class="report-section-heading report-catalog-heading">
          <div><span class="step-label">经营资料接入</span><h3>提交原始资料，系统映射、检查并留存版本</h3></div>
          <span>${Number(operatingEvidence.passedTypeCount || 0)}/${Number(operatingEvidence.totalTypeCount || evidenceCategories.length)}类已通过试算</span>
        </div>
        <div class="operating-evidence-grid">${evidenceCategories.map((item) => `
          <article class="operating-evidence-card ${item.latestFile ? "received" : "missing"}">
            <div class="operating-evidence-heading">
              <div><b>${escapeHtml(item.taskId)}</b><strong>${escapeHtml(item.label)}</strong></div>
              <span class="report-item-status status-${item.run?.status === "passed" ? "available" : item.latestFile ? "partial" : "missing"}">${escapeHtml(item.statusLabel)}</span>
            </div>
            <p>${escapeHtml(item.guidance)}</p>
            <div class="operating-evidence-latest">
              ${item.latestFile
                ? `<strong>${escapeHtml(item.latestFile.originalName)}</strong><span>${item.run ? `${Number(item.run.matchedRowCount || 0).toLocaleString("zh-CN")}行已匹配 · ${formatOptionalMoney(item.run.totalAmountCents)} · ${escapeHtml(item.run.mappingVersion)}` : `第${Number(item.versionCount || 1)}个版本 · 只留存，尚未进入利润`}</span>`
                : `<strong>尚未提交</strong><span>${escapeHtml(item.unlock)}</span>`}
            </div>
            ${item.run ? `<button class="evidence-detail-button" type="button" data-operating-detail="${escapeHtml(item.code)}">查看映射明细</button>` : ""}
            <form class="operating-evidence-form" data-evidence-type="${escapeHtml(item.code)}">
              <label>资料文件
                <input name="file" type="file" accept=".xlsx,.csv" required ${reportReadOnly ? "disabled" : ""} />
              </label>
              <label>替换说明${item.versionCount ? "（再次提交必填）" : "（首次可不填）"}
                <input name="replacementReason" maxlength="300" placeholder="例如：补齐退货入库记录" ${reportReadOnly ? "disabled" : ""} />
              </label>
              <button class="secondary-button compact-button" type="submit" ${reportReadOnly ? "disabled" : ""}>${item.versionCount ? "提交新版本" : "提交资料"}</button>
              <p class="form-message" role="status"></p>
            </form>
          </article>`).join("")}</div>
        <div class="config-boundary-note"><strong>当前边界</strong><span>${escapeHtml(operatingEvidence.scopeNotice || "收到文件后仍需完成映射和口径检查，才会进入利润核算。")}</span></div>
      </section>

      <section class="report-panel">
        <div class="report-section-heading report-catalog-heading">
          <div><span class="step-label">报表规划</span><h3>已有、待开发与不在当前范围</h3></div>
          <button class="secondary-button compact-button" type="button" data-report-action="reconcile">查看对账宽表</button>
        </div>
        <div class="report-catalog">${reports.map((item) => `
          <div>
            <span class="report-item-status status-${escapeHtml(item.status)}">${escapeHtml(item.statusLabel)}</span>
            <strong>${escapeHtml(item.label)}</strong>
            <p>${escapeHtml(item.description)}</p>
          </div>`).join("")}</div>
      </section>
    </article>`;
  bindOperatingReportActions();
}

function bindOperatingReportActions() {
  elements.operatingReportContent.querySelectorAll("[data-report-action]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.reportAction));
  });
  elements.operatingReportContent.querySelectorAll(".operating-evidence-form").forEach((form) => {
    form.addEventListener("submit", submitOperatingEvidence);
  });
  elements.operatingReportContent.querySelectorAll("[data-operating-detail]").forEach((button) => {
    button.addEventListener("click", () => openOperatingEvidenceDetail(button.dataset.operatingDetail));
  });
}

async function submitOperatingEvidence(event) {
  event.preventDefault();
  if (!selectedTaskId) return;
  const form = event.currentTarget;
  const file = form.elements.file.files[0];
  const message = form.querySelector(".form-message");
  message.textContent = "";
  message.classList.remove("error");
  if (!file || !/\.(xlsx|csv)$/i.test(file.name)) {
    message.textContent = "请选择.xlsx或.csv文件。";
    message.classList.add("error");
    return;
  }
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "正在留存……";
  try {
    const reason = form.elements.replacementReason.value.trim();
    const headers = { "X-File-Name": encodeURIComponent(file.name) };
    if (reason) headers["X-Replacement-Reason"] = encodeURIComponent(reason);
    await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/operating-evidence/${encodeURIComponent(form.dataset.evidenceType)}/files`,
      { method: "POST", headers, body: file }
    );
    await loadOperatingReport();
  } catch (error) {
    message.textContent = error.message;
    message.classList.add("error");
    button.disabled = false;
    button.textContent = "重新提交";
  }
}

async function openOperatingEvidenceDetail(evidenceType, page = 1) {
  if (!selectedTaskId) return;
  closeLifecycleDialog();
  const overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeLifecycleDialog();
  });
  const dialog = document.createElement("section");
  dialog.className = "operating-evidence-dialog";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "经营资料映射明细");
  dialog.innerHTML = '<div class="state-box compact">正在读取映射明细……</div>';
  overlay.append(dialog);
  document.body.append(overlay);
  document.body.classList.add("modal-open");
  try {
    const result = await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/operating-evidence/${encodeURIComponent(evidenceType)}/results?page=${page}&pageSize=50`
    );
    renderOperatingEvidenceDetail(dialog, evidenceType, result);
  } catch (error) {
    dialog.innerHTML = `<div class="dialog-header"><div><h2>经营资料映射明细</h2><p>暂时无法读取</p></div><button type="button" class="detail-close" aria-label="关闭">×</button></div><p class="dialog-error">${escapeHtml(error.message)}</p>`;
    dialog.querySelector(".detail-close").addEventListener("click", closeLifecycleDialog);
  }
}

function renderOperatingEvidenceDetail(dialog, evidenceType, result) {
  const run = result.run || {};
  const pagination = result.pagination || {};
  const rows = result.rows || [];
  dialog.innerHTML = `
    <div class="dialog-header">
      <div><h2>${escapeHtml(result.label)}·映射明细</h2><p>${escapeHtml(run.originalName || "")} · ${escapeHtml(run.mappingVersion || "")} · 模拟试算</p></div>
      <button type="button" class="detail-close" aria-label="关闭">×</button>
    </div>
    <div class="evidence-detail-summary">
      <div><span>原始行</span><strong>${Number(run.totalRowCount || 0).toLocaleString("zh-CN")}</strong></div>
      <div><span>已匹配</span><strong>${Number(run.matchedRowCount || 0).toLocaleString("zh-CN")}</strong></div>
      <div><span>需检查</span><strong>${Number(run.attentionCount || 0).toLocaleString("zh-CN")}</strong></div>
      <div><span>试算金额</span><strong>${formatOptionalMoney(run.totalAmountCents)}</strong></div>
    </div>
    <div class="evidence-detail-table-scroll">
      <table class="evidence-detail-table">
        <thead><tr><th>Excel行</th><th>主标识</th><th>辅助信息</th><th>金额</th><th>状态</th><th>原始字段</th><th>说明</th></tr></thead>
        <tbody>${rows.map((row) => `
          <tr>
            <td>${Number(row.rowNumber || 0)}</td>
            <td class="identifier-cell">${escapeHtml(row.primaryIdentifier || "—")}</td>
            <td>${escapeHtml(row.secondaryIdentifier || "—")}</td>
            <td class="report-money">${formatOptionalMoney(row.amountCents)}</td>
            <td><span class="report-item-status status-${row.status === "matched" ? "available" : "needs_attention"}">${escapeHtml(row.statusLabel)}</span></td>
            <td><details><summary>查看原值</summary><div class="raw-value-grid">${Object.entries(row.rawValues || {}).map(([key, value]) => `<span><b>${escapeHtml(key)}</b>${escapeHtml(value)}</span>`).join("")}</div></details></td>
            <td>${escapeHtml(row.explanation)}</td>
          </tr>`).join("")}</tbody>
      </table>
    </div>
    <div class="evidence-detail-pagination">
      <span>第${Number(pagination.page || 1)} / ${Number(pagination.totalPages || 1)}页 · 共${Number(pagination.total || 0).toLocaleString("zh-CN")}行</span>
      <div>
        <button type="button" class="secondary-button compact-button" data-detail-page="${Number(pagination.page || 1) - 1}" ${Number(pagination.page || 1) <= 1 ? "disabled" : ""}>上一页</button>
        <button type="button" class="secondary-button compact-button" data-detail-page="${Number(pagination.page || 1) + 1}" ${Number(pagination.page || 1) >= Number(pagination.totalPages || 1) ? "disabled" : ""}>下一页</button>
      </div>
    </div>`;
  dialog.querySelector(".detail-close").addEventListener("click", closeLifecycleDialog);
  dialog.querySelectorAll("[data-detail-page]").forEach((button) => {
    button.addEventListener("click", () => openOperatingEvidenceDetail(evidenceType, Number(button.dataset.detailPage)));
  });
}

function formatOptionalMoney(cents) {
  return cents === null || cents === undefined ? "—" : formatMoney(cents);
}

function setTaskReadOnly(readOnly) {
  [
    ...elements.uploadForm.elements,
    ...elements.platformBalanceForm.elements,
    ...elements.pendingSettlementForm.elements,
  ].forEach((control) => {
    control.disabled = readOnly;
  });
  elements.uploadForm.classList.toggle("read-only", readOnly);
  elements.platformBalanceForm.classList.toggle("read-only", readOnly);
  elements.pendingSettlementForm.classList.toggle("read-only", readOnly);
  if (readOnly) {
    elements.uploadMessage.classList.remove("error");
    elements.uploadMessage.textContent = "本期已完成，数据和人工处理结果仅供查看；需修改请先重新打开。";
    elements.platformBalanceMessage.classList.remove("error");
    elements.platformBalanceMessage.textContent = "本期已完成，补充资料仅供查看。";
    elements.pendingSettlementMessage.classList.remove("error");
    elements.pendingSettlementMessage.textContent = "本期已完成，待结算跟踪仅供查看。";
  }
}

function setImportDetailState(target) {
  [elements.detailLoading, elements.fileEmpty, elements.fileResult].forEach((element) => {
    element.hidden = element !== target;
  });
}

function renderImportPage(files) {
  elements.goToReconcileButton.hidden = true;
  if (!files.length) {
    selectedFileId = null;
    setImportDetailState(elements.fileEmpty);
    return;
  }
  renderImportInspection(files[0], files.length);
}

function renderPlatformBalanceImport(platformBalance) {
  elements.platformBalanceImportSummary.innerHTML = "";
  if (!platformBalance) {
    elements.platformBalanceImportSummary.innerHTML = "<span>尚未导入平台账户日/月汇总。</span>";
    return;
  }
  const latest = platformBalance.latestFile;
  const run = platformBalance.run;
  const card = document.createElement("div");
  card.className = `supporting-import-result ${latest.inspectionStatus}`;
  const title = latest.inspectionStatus === "passed"
    ? "最新补充资料已检查"
    : "最新补充资料结构不符合当前映射";
  card.innerHTML = `
    <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(latest.originalName)} · ${escapeHtml(latest.mappingVersion)}</span></div>
    <b>${run ? `${run.attentionCount.toLocaleString("zh-CN")}项待核` : "未运行"}</b>`;
  elements.platformBalanceImportSummary.append(card);
  if (latest.inspection.errors && latest.inspection.errors.length) {
    const list = document.createElement("ul");
    list.className = "inspection-errors compact-errors";
    latest.inspection.errors.forEach((message) => {
      const item = document.createElement("li");
      item.textContent = message;
      list.append(item);
    });
    elements.platformBalanceImportSummary.append(list);
  }
}

function renderPendingSettlementImport(pendingSettlement) {
  elements.pendingSettlementImportSummary.innerHTML = "";
  if (!pendingSettlement) {
    elements.pendingSettlementImportSummary.innerHTML = "<span>尚未导入待结算订单资料。</span>";
    return;
  }
  const latest = pendingSettlement.latestFile;
  const run = pendingSettlement.run;
  const card = document.createElement("div");
  card.className = `supporting-import-result ${latest.inspectionStatus}`;
  const title = latest.inspectionStatus === "passed"
    ? "待结算资料已分类"
    : "待结算资料不符合当前映射";
  card.innerHTML = `
    <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(latest.originalName)} · ${escapeHtml(latest.mappingVersion)}</span></div>
    <b>${run ? `${run.attentionCount.toLocaleString("zh-CN")}笔需跟踪` : "未运行"}</b>`;
  elements.pendingSettlementImportSummary.append(card);
  if (latest.inspection.errors && latest.inspection.errors.length) {
    const list = document.createElement("ul");
    list.className = "inspection-errors compact-errors";
    latest.inspection.errors.forEach((message) => {
      const item = document.createElement("li");
      item.textContent = message;
      list.append(item);
    });
    elements.pendingSettlementImportSummary.append(list);
  }
}

function renderImportInspection(file, versionCount) {
  const inspection = file.inspection;
  selectedFileId = file.id;
  elements.fileResult.innerHTML = "";

  const summary = document.createElement("div");
  summary.className = `inspection-summary ${inspection.status}`;
  const summaryText = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = inspection.status === "passed" ? "文件结构检查通过" : "文件需要处理";
  const detail = document.createElement("span");
  const templateLabel = file.templateVersionLabel ? ` · 账单模板${file.templateVersionLabel}` : "";
  detail.textContent = `${file.originalName} · ${formatBytes(file.sizeBytes)} · 第${versionCount}个留存版本${templateLabel}`;
  summaryText.append(title, detail);
  const badge = document.createElement("span");
  badge.className = "result-badge";
  badge.textContent = `${inspection.foundRequiredSheetCount}/${inspection.requiredSheetCount}张表`;
  summary.append(summaryText, badge);
  elements.fileResult.append(summary);

  if (inspection.errors.length) {
    const errorList = document.createElement("ul");
    errorList.className = "inspection-errors";
    inspection.errors.forEach((message) => {
      const item = document.createElement("li");
      item.textContent = message;
      errorList.append(item);
    });
    elements.fileResult.append(errorList);
  }

  if (file.dataImport) {
    renderImportSummary(file.id, file.dataImport, elements.fileResult);
    renderIssueGroups(file.dataImport, elements.fileResult, "导入质量问题", file);
    elements.goToReconcileButton.hidden = false;
  } else {
    renderStructureCards(inspection, elements.fileResult);
  }
  setImportDetailState(elements.fileResult);
}

function renderStructureCards(inspection, container) {
  const grid = document.createElement("div");
  grid.className = "structure-grid";
  inspection.sheets.forEach((sheet) => {
    const card = document.createElement("article");
    card.className = `structure-card ${sheet.status}`;
    const name = document.createElement("strong");
    name.textContent = sheet.name;
    const state = document.createElement("span");
    state.textContent = sheet.status === "passed" ? "通过" : "需处理";
    const metrics = document.createElement("p");
    metrics.textContent = sheet.present ? `${sheet.dataRowCount.toLocaleString("zh-CN")}行 · ${sheet.columnCount}列` : "未找到这张表";
    card.append(name, state, metrics);
    grid.append(card);
  });
  container.append(grid);
}

function renderImportSummary(fileId, dataImport, container) {
  const section = document.createElement("section");
  section.className = "import-summary-section";
  const heading = document.createElement("div");
  heading.className = "section-title-row";
  const text = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = dataImport.status === "failed" ? "数据已保存，存在阻断" : "逐行数据已保存";
  const meta = document.createElement("p");
  meta.textContent = `共${dataImport.totalRecordCount.toLocaleString("zh-CN")}行 · ${dataImport.blockingIssueCount}个阻断 · ${dataImport.warningIssueCount}个提醒`;
  text.append(title, meta);
  const state = document.createElement("span");
  state.className = `data-state ${dataImport.status}`;
  state.textContent = dataImport.status === "failed" ? "需处理" : "已导入";
  heading.append(text, state);
  section.append(heading);

  const list = document.createElement("div");
  list.className = "import-sheet-list";
  dataImport.sheetSummaries.forEach((sheet) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "import-sheet-row";
    row.addEventListener("click", () => {
      switchView("reconcile");
      activateReconcileTab(fileId, sheet.name, 1);
    });
    const name = document.createElement("strong");
    name.textContent = sheet.name;
    const volume = document.createElement("span");
    volume.textContent = `${sheet.recordCount.toLocaleString("zh-CN")}行 · 源文件${sheet.columnCount || 0}列`;
    const amount = document.createElement("span");
    amount.className = "sheet-amount";
    amount.textContent = formatAmountSummary(sheet.amountSummary);
    const action = document.createElement("span");
    action.className = "row-action";
    action.textContent = "查看明细 →";
    row.append(name, volume, amount, action);
    list.append(row);
  });
  section.append(list);
  container.append(section);
}

function renderReconciliationPage(files) {
  if (!files.length || !files[0].dataImport) {
    elements.reconcileEmpty.hidden = false;
    elements.reconcileContent.hidden = true;
    elements.reconcileKpis.hidden = true;
    elements.recordTabs.innerHTML = "";
    elements.reconcileOverview.innerHTML = "";
    elements.reconciliationBrowser.innerHTML = "";
    elements.recordBrowser.innerHTML = "";
    return;
  }

  const file = files[0];
  selectedFileId = file.id;
  elements.reconcileEmpty.hidden = true;
  elements.reconcileContent.hidden = false;
  renderReconcileKpis(file, selectedTaskDetail && selectedTaskDetail.completion);
  elements.reconcileKpis.hidden = activeView !== "reconcile";
  renderRecordTabs(file);
  renderReconcileOverview(file);

  const validSheet = selectedSheetName && file.dataImport.sheetSummaries.some((sheet) => sheet.name === selectedSheetName);
  const validReconciliation =
    selectedSheetName === wideReconciliationTab
    || selectedSheetName === platformBalanceTab
    || selectedSheetName === pendingSettlementTab
    || (selectedSheetName === ordinaryReconciliationTab && file.reconciliation)
    || (selectedSheetName === refundReconciliationTab && file.refundReconciliation);
  const validSupplementary = supplementaryResultTabs[selectedSheetName]
    && file.supplementaryReconciliation;
  const initialTab = validSheet
    ? selectedSheetName
    : validReconciliation || validSupplementary
      ? selectedSheetName
      : wideReconciliationTab;
  activateReconcileTab(file.id, initialTab, 1);
}

function renderReconcileKpis(file, completion) {
  const dataImport = file.dataImport;
  const checks = file.amountChecks;
  const reconciliation = file.reconciliation;
  const refund = file.refundReconciliation;
  const supplementary = file.supplementaryReconciliation;
  elements.reconcileKpis.innerHTML = "";
  const totalResults = (reconciliation ? reconciliation.totalResultCount : 0) + (refund ? refund.totalResultCount : 0);
  const totalMatched = (reconciliation ? reconciliation.matchedCount : 0) + (refund ? refund.matchedCount : 0);
  const totalAttention = (reconciliation ? reconciliation.attentionCount : 0) + (refund ? refund.attentionCount : 0);
  const items = completion && completion.systemAttentionCount
    ? [
        ["系统待处理", `${completion.systemAttentionCount.toLocaleString("zh-CN")}笔`],
        ["人工已处理", `${completion.resolvedCount.toLocaleString("zh-CN")}笔`],
        ["带到下月", `${completion.carriedForwardCount.toLocaleString("zh-CN")}笔`],
        ["仍未处理", `${completion.unresolvedCount.toLocaleString("zh-CN")}笔`],
      ]
    : supplementary
    ? [
        ["结算核对", `${totalMatched.toLocaleString("zh-CN")}/${totalResults.toLocaleString("zh-CN")}笔`],
        ["缺历史订单", `${supplementary.crossMonth.missingHistoricalOrderCount.toLocaleString("zh-CN")}笔`],
        ["成本待补", `${supplementary.costs.attentionCount.toLocaleString("zh-CN")}笔`],
        ["未分类收支", `${supplementary.otherFunds.attentionCount.toLocaleString("zh-CN")}笔`],
      ]
    : reconciliation || refund
    ? [
        ["已核对", `${totalMatched.toLocaleString("zh-CN")}/${totalResults.toLocaleString("zh-CN")}笔`],
        ["普通结算", `${reconciliation ? reconciliation.totalResultCount.toLocaleString("zh-CN") : 0}笔`],
        ["退款结算", `${refund ? refund.totalResultCount.toLocaleString("zh-CN") : 0}笔`],
        ["待处理", `${totalAttention.toLocaleString("zh-CN")}笔`],
      ]
    : [
        ["导入数据", `${dataImport.totalRecordCount.toLocaleString("zh-CN")}行`],
        ["阻断", `${dataImport.blockingIssueCount}个`],
        ["提醒", `${dataImport.warningIssueCount}个`],
        ["金额检查", checks ? `${checks.passedCount.toLocaleString("zh-CN")}/${checks.totalCheckCount.toLocaleString("zh-CN")}` : "待检查"],
      ];
  items.forEach(([label, value]) => {
    const item = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = value;
    const span = document.createElement("span");
    span.textContent = label;
    item.append(strong, span);
    elements.reconcileKpis.append(item);
  });
}

function renderRecordTabs(file) {
  const fileId = file.id;
  const dataImport = file.dataImport;
  elements.recordTabs.innerHTML = "";
  const overview = document.createElement("button");
  overview.type = "button";
  overview.className = "secondary-tab";
  overview.dataset.sheetName = "";
  overview.textContent = "对账总览";
  overview.addEventListener("click", () => activateReconcileTab(fileId, null));
  elements.recordTabs.append(overview);

  const wide = document.createElement("button");
  wide.type = "button";
  wide.className = "secondary-tab result-tab wide-result-tab";
  wide.dataset.sheetName = wideReconciliationTab;
  const wideName = document.createElement("span");
  wideName.textContent = "对账明细";
  const wideCount = document.createElement("b");
  wideCount.textContent = dataImport.sheetSummaries
    .find((sheet) => sheet.name === "订单明细")
    ?.recordCount.toLocaleString("zh-CN") || "—";
  wide.append(wideName, wideCount);
  wide.addEventListener("click", () => activateReconcileTab(fileId, wideReconciliationTab, 1));
  elements.recordTabs.append(wide);

  const balance = document.createElement("button");
  balance.type = "button";
  balance.className = "secondary-tab result-tab";
  balance.dataset.sheetName = platformBalanceTab;
  const balanceName = document.createElement("span");
  balanceName.textContent = "资料完整性";
  const balanceCount = document.createElement("b");
  const platformRun = selectedTaskDetail && selectedTaskDetail.platformBalance
    && selectedTaskDetail.platformBalance.run;
  balanceCount.textContent = platformRun
    ? platformRun.attentionCount.toLocaleString("zh-CN")
    : "未导入";
  balance.append(balanceName, balanceCount);
  balance.addEventListener("click", () => activateReconcileTab(fileId, platformBalanceTab, 1));
  elements.recordTabs.append(balance);

  const pending = document.createElement("button");
  pending.type = "button";
  pending.className = "secondary-tab result-tab";
  pending.dataset.sheetName = pendingSettlementTab;
  const pendingName = document.createElement("span");
  pendingName.textContent = "待结算跟踪";
  const pendingCount = document.createElement("b");
  const pendingRun = selectedTaskDetail && selectedTaskDetail.pendingSettlement
    && selectedTaskDetail.pendingSettlement.run;
  pendingCount.textContent = pendingRun
    ? pendingRun.attentionCount.toLocaleString("zh-CN")
    : "未导入";
  pending.append(pendingName, pendingCount);
  pending.addEventListener("click", () => activateReconcileTab(fileId, pendingSettlementTab, 1));
  elements.recordTabs.append(pending);

  const rawPicker = document.createElement("label");
  rawPicker.className = "raw-table-picker";
  const rawLabel = document.createElement("span");
  rawLabel.textContent = "原始数据";
  const rawSelect = document.createElement("select");
  rawSelect.setAttribute("aria-label", "选择原始数据表");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "选择明细表";
  rawSelect.append(placeholder);
  dataImport.sheetSummaries.forEach((sheet) => {
    const option = document.createElement("option");
    option.value = sheet.name;
    option.textContent = `${sheet.name} · ${sheet.recordCount.toLocaleString("zh-CN")}`;
    rawSelect.append(option);
  });
  rawSelect.value = dataImport.sheetSummaries.some((sheet) => sheet.name === selectedSheetName)
    ? selectedSheetName
    : "";
  rawSelect.addEventListener("change", () => {
    if (rawSelect.value) activateReconcileTab(fileId, rawSelect.value, 1);
  });
  rawPicker.append(rawLabel, rawSelect);
  elements.recordTabs.append(rawPicker);
}

function renderReconcileOverview(file) {
  elements.reconcileOverview.innerHTML = "";
  const resultSection = document.createElement("section");
  resultSection.className = "overview-section";
  const resultHeading = document.createElement("div");
  resultHeading.className = "overview-section-heading";
  resultHeading.innerHTML = "<div><h2>本次对账结果</h2><p>普通结算、退款结算、订单与结算、售后、成本和其他收支分别核对，异常统一进入对账宽表处理。</p></div>";
  resultSection.append(resultHeading);
  if (file.reconciliation) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `ordinary-overview-card ${file.reconciliation.status}`;
    card.addEventListener("click", () => openWideScene(file.id, "ordinary_settlement"));
    card.innerHTML = `
      <div><span>普通结算</span><strong>${file.reconciliation.matchedCount.toLocaleString("zh-CN")}/${file.reconciliation.totalResultCount.toLocaleString("zh-CN")} 笔一致</strong></div>
      <div><span>结算账单</span><b>${formatMoney(file.reconciliation.settlementAmountTotalCents)}</b></div>
      <div><span>已匹配资金</span><b>${formatMoney(file.reconciliation.matchedFundAmountTotalCents)}</b></div>
      <div><span>待处理</span><b>${file.reconciliation.attentionCount.toLocaleString("zh-CN")} 笔</b></div>
      <em>查看核对结果与原始行 →</em>`;
    resultSection.append(card);
  } else {
    const pending = document.createElement("div");
    pending.className = "reconciliation-unavailable-card";
    const blocked = file.dataImport.status === "failed";
    pending.innerHTML = `<strong>${blocked ? "存在导入阻断，普通结算未运行" : "普通结算结果尚未生成"}</strong><span>${blocked ? "先修正导入页提示的数据问题；已保存的底表仍可查看。" : "重新启动本机应用后会自动补算已有数据。"}</span>`;
    resultSection.append(pending);
  }
  if (file.refundReconciliation) {
    const refundCard = document.createElement("button");
    refundCard.type = "button";
    refundCard.className = `ordinary-overview-card ${file.refundReconciliation.status}`;
    refundCard.addEventListener("click", () => openWideScene(file.id, "refund_settlement"));
    refundCard.innerHTML = `
      <div><span>退款结算</span><strong>${file.refundReconciliation.matchedCount.toLocaleString("zh-CN")}/${file.refundReconciliation.totalResultCount.toLocaleString("zh-CN")} 笔一致</strong></div>
      <div><span>退款结算净额</span><b>${formatMoney(file.refundReconciliation.settlementAmountTotalCents)}</b></div>
      <div><span>已归组资金净额</span><b>${formatMoney(file.refundReconciliation.matchedFundAmountTotalCents)}</b></div>
      <div><span>待处理</span><b>${file.refundReconciliation.attentionCount.toLocaleString("zh-CN")} 笔</b></div>
      <em>查看退款组与原始行 →</em>`;
    resultSection.append(refundCard);
  }
  if (file.supplementaryReconciliation) {
    const supplementary = file.supplementaryReconciliation;
    const grid = document.createElement("div");
    grid.className = "supplementary-overview-grid";
    const cards = [
      ["__cross_month__", "订单与结算", `${(supplementary.crossMonth.receivableMismatchCount || 0).toLocaleString("zh-CN")}笔应收差异`, `${(supplementary.crossMonth.possiblyUnsettledCount || 0).toLocaleString("zh-CN")}笔可能未结算`],
      ["__after_sale__", "售后状态", `${supplementary.afterSales.refundSuccessCount.toLocaleString("zh-CN")}笔退款成功`, `${((supplementary.afterSales.refundConflictCount || 0) + (supplementary.afterSales.refundMissingAfterSaleCount || 0)).toLocaleString("zh-CN")}笔退款证据冲突`],
      ["__cost_link__", "成本关联", `${supplementary.costs.matchedCount.toLocaleString("zh-CN")}行已关联`, `${supplementary.costs.attentionCount.toLocaleString("zh-CN")}行待补资料`],
      ["__other_fund__", "其他收支", `${supplementary.otherFunds.classifiedCount.toLocaleString("zh-CN")}笔已分类`, `${supplementary.otherFunds.attentionCount.toLocaleString("zh-CN")}笔等待分类`],
    ];
    cards.forEach(([tabKey, label, main, detail]) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "supplementary-overview-card";
      card.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(main)}</strong><small>${escapeHtml(detail)}</small><em>查看明细 →</em>`;
      card.addEventListener("click", () => openWideScene(file.id, supplementaryResultTabs[tabKey].resultType));
      grid.append(card);
    });
    resultSection.append(grid);
  }
  const platformBalance = selectedTaskDetail && selectedTaskDetail.platformBalance;
  const balanceCard = document.createElement("button");
  balanceCard.type = "button";
  balanceCard.className = "platform-balance-overview-card";
  balanceCard.addEventListener("click", () => activateReconcileTab(file.id, platformBalanceTab, 1));
  if (platformBalance && platformBalance.run) {
    const run = platformBalance.run;
    balanceCard.innerHTML = `
      <div><span>平台账户完整性</span><strong>${run.matchedCount.toLocaleString("zh-CN")}/${run.totalResultCount.toLocaleString("zh-CN")} 项一致</strong></div>
      <div><span>试运行待核</span><b>${run.attentionCount.toLocaleString("zh-CN")} 项</b></div>
      <em>模拟字段映射 · 暂不阻断完成本期 →</em>`;
  } else {
    balanceCard.innerHTML = `
      <div><span>平台账户完整性</span><strong>尚未导入日/月汇总</strong></div>
      <div><span>当前能力</span><b>仅逐笔资金</b></div>
      <em>补充汇总后检查漏行、漏日和余额 →</em>`;
  }
  resultSection.append(balanceCard);
  const pendingSettlement = selectedTaskDetail && selectedTaskDetail.pendingSettlement;
  const pendingCard = document.createElement("button");
  pendingCard.type = "button";
  pendingCard.className = "platform-balance-overview-card pending-settlement-overview-card";
  pendingCard.addEventListener("click", () => activateReconcileTab(file.id, pendingSettlementTab, 1));
  if (pendingSettlement && pendingSettlement.run) {
    const run = pendingSettlement.run;
    pendingCard.innerHTML = `
      <div><span>待结算跟踪</span><strong>${run.totalResultCount.toLocaleString("zh-CN")} 笔已分类</strong></div>
      <div><span>需跟踪</span><b>${run.attentionCount.toLocaleString("zh-CN")} 笔</b></div>
      <div><span>正常等待</span><b>${run.waitingCount.toLocaleString("zh-CN")} 笔</b></div>
      <em>查看每笔原因和源Excel行 →</em>`;
  } else {
    pendingCard.innerHTML = `
      <div><span>待结算跟踪</span><strong>尚未导入</strong></div>
      <div><span>可识别</span><b>等待 / 逾期 / 售后 / 限制</b></div>
      <em>补充待结算资料后分类 →</em>`;
  }
  resultSection.append(pendingCard);
  elements.reconcileOverview.append(resultSection);

  const coverage = document.createElement("section");
  coverage.className = "overview-section";
  const title = document.createElement("div");
  title.className = "overview-section-heading";
  title.innerHTML = "<div><h2>导入数据总览</h2><p>点击任意一张表进入对应明细。</p></div>";
  coverage.append(title);
  const grid = document.createElement("div");
  grid.className = "overview-sheet-grid";
  file.dataImport.sheetSummaries.forEach((sheet) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "overview-sheet-card";
    card.addEventListener("click", () => activateReconcileTab(file.id, sheet.name, 1));
    const top = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = sheet.name;
    const arrow = document.createElement("span");
    arrow.textContent = "→";
    top.append(name, arrow);
    const count = document.createElement("b");
    count.textContent = `${sheet.recordCount.toLocaleString("zh-CN")}行`;
    const amount = document.createElement("small");
    amount.textContent = formatAmountSummary(sheet.amountSummary);
    const quality = document.createElement("em");
    quality.textContent = `${sheet.blockingIssueCount}阻断 · ${sheet.warningIssueCount}提醒`;
    card.append(top, count, amount, quality);
    grid.append(card);
  });
  coverage.append(grid);
  elements.reconcileOverview.append(coverage);

  renderAmountChecks(file.amountChecks, elements.reconcileOverview);
  renderIssueGroups(file.dataImport, elements.reconcileOverview, "需要关注的数据问题", file);
}

function activateReconcileTab(fileId, sheetName, page = 1) {
  selectedFileId = fileId;
  selectedSheetName = sheetName;
  if (sheetName !== wideReconciliationTab) {
    elements.reconciliationBrowser.classList.remove("wide-reconciliation-browser");
  }
  elements.recordTabs.querySelectorAll(".secondary-tab").forEach((tab) => {
    const selected = tab.dataset.sheetName === (sheetName || "");
    tab.classList.toggle("selected", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  const rawSelect = elements.recordTabs.querySelector(".raw-table-picker select");
  if (rawSelect) {
    const file = selectedTaskDetail && selectedTaskDetail.files.find((item) => item.id === fileId);
    const isRawSheet = file && file.dataImport.sheetSummaries.some((sheet) => sheet.name === sheetName);
    rawSelect.value = isRawSheet ? sheetName : "";
  }
  const isOverview = !sheetName;
  const supplementaryConfig = supplementaryResultTabs[sheetName];
  const isReconciliation = sheetName === wideReconciliationTab
    || sheetName === platformBalanceTab
    || sheetName === pendingSettlementTab
    || sheetName === ordinaryReconciliationTab
    || sheetName === refundReconciliationTab
    || Boolean(supplementaryConfig);
  elements.reconcileOverview.hidden = !isOverview;
  elements.reconciliationPane.hidden = !isReconciliation;
  elements.recordPane.hidden = isOverview || isReconciliation;
  if (isReconciliation) {
    const file = selectedTaskDetail && selectedTaskDetail.files.find((item) => item.id === fileId);
    if (sheetName === wideReconciliationTab) {
      openWideReconciliation(fileId, selectedWideFilter, selectedWideScene, selectedWideQuery, page);
    } else if (sheetName === platformBalanceTab) {
      openPlatformBalanceResults(selectedPlatformBalanceFilter, page);
    } else if (sheetName === pendingSettlementTab) {
      openPendingSettlementResults(selectedPendingSettlementFilter, page);
    } else if (sheetName === refundReconciliationTab && file && file.refundReconciliation) {
      openRefundReconciliation(fileId, selectedReconciliationFilter, page);
    } else if (sheetName === ordinaryReconciliationTab && file && file.reconciliation) {
      openOrdinaryReconciliation(fileId, selectedReconciliationFilter, page);
    } else if (supplementaryConfig && file && file.supplementaryReconciliation) {
      openSupplementaryResults(fileId, supplementaryConfig.resultType, selectedSupplementaryFilter, page);
    } else {
      const label = supplementaryConfig
        ? supplementaryConfig.label
        : sheetName === refundReconciliationTab ? "退款结算" : "普通结算";
      renderReconciliationUnavailable(file, label);
    }
  } else if (!isOverview) {
    openSheet(fileId, sheetName, page);
  }
}

function renderReconciliationUnavailable(file, resultLabel = "普通结算") {
  elements.reconciliationBrowser.innerHTML = "";
  const state = document.createElement("div");
  state.className = "state-box compact reconciliation-unavailable";
  const title = document.createElement("strong");
  const detail = document.createElement("span");
  const blocked = file && file.dataImport && file.dataImport.status === "failed";
  title.textContent = blocked ? `${resultLabel}核对未运行` : `暂时没有${resultLabel}结果`;
  detail.textContent = blocked
    ? "这次导入存在阻断。可在当前界面按系统识别结果修正，或到数据导入页查看具体 Excel 行。"
    : "结果尚未生成；重新启动本机应用后会自动补算已有的可用数据。";
  state.append(title, detail);
  const mismatch = getTaskPeriodMismatch(file && file.dataImport);
  if (blocked && mismatch) {
    state.append(createPeriodCorrectionButton(mismatch.targetPeriod));
    const auditNote = document.createElement("small");
    auditNote.textContent = "会生成修正后的新任务并重新检查；原任务、原文件和原导入结果全部保留。";
    state.append(auditNote);
  }
  elements.reconciliationBrowser.append(state);
}

async function openPlatformBalanceResults(status = "all", page = 1) {
  selectedPlatformBalanceFilter = status;
  elements.reconciliationBrowser.classList.remove("wide-reconciliation-browser");
  elements.reconciliationBrowser.innerHTML = "";
  const platformBalance = selectedTaskDetail && selectedTaskDetail.platformBalance;
  if (!platformBalance || !platformBalance.run) {
    const state = document.createElement("div");
    state.className = "state-box compact reconciliation-unavailable";
    state.innerHTML = "<strong>尚未导入平台账户日/月汇总</strong><span>当前只能证明已导入的逐笔资金可以核对，不能证明平台导出没有漏行或漏日。</span>";
    const action = document.createElement("button");
    action.type = "button";
    action.className = "primary-button inline-button";
    action.textContent = "去补充资料";
    action.addEventListener("click", () => switchView("import"));
    state.append(action);
    elements.reconciliationBrowser.append(state);
    return;
  }
  elements.reconciliationBrowser.innerHTML = '<div class="state-box compact">正在核对平台账户完整性……</div>';
  try {
    const data = await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/platform-balance-results?status=${encodeURIComponent(status)}&page=${page}&pageSize=${selectedPlatformBalancePageSize}`
    );
    elements.reconciliationBrowser.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "reconciliation-heading platform-balance-heading";
    heading.innerHTML = `
      <div><h2>平台账户完整性</h2><p>逐笔资金 ↔ 日汇总 ↔ 月汇总；笔数、收入、支出、余额和日期覆盖必须同时成立。</p></div>
      <span class="trial-badge">${escapeHtml(data.summary.mappingVersion)} · 试运行不阻断</span>`;
    elements.reconciliationBrowser.append(heading);

    const notice = document.createElement("div");
    notice.className = "trial-notice";
    notice.textContent = platformBalance.notice;
    elements.reconciliationBrowser.append(notice);

    const metrics = document.createElement("div");
    metrics.className = "platform-balance-metrics";
    [
      ["检查项", data.summary.totalResultCount],
      ["核对一致", data.summary.matchedCount],
      ["试运行待核", data.summary.attentionCount],
      ["缺少日汇总", data.summary.dateGapCount],
    ].forEach(([label, value]) => {
      const item = document.createElement("div");
      item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${Number(value || 0).toLocaleString("zh-CN")}</strong>`;
      metrics.append(item);
    });
    elements.reconciliationBrowser.append(metrics);

    const toolbar = document.createElement("div");
    toolbar.className = "platform-balance-toolbar";
    const filters = document.createElement("div");
    filters.className = "filter-pills";
    [
      ["all", `全部 ${data.summary.totalResultCount}`],
      ["attention", `待核 ${data.summary.attentionCount}`],
      ["matched", `一致 ${data.summary.matchedCount}`],
    ].forEach(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = key === status ? "selected" : "";
      button.textContent = label;
      button.addEventListener("click", () => openPlatformBalanceResults(key, 1));
      filters.append(button);
    });
    const pageSize = document.createElement("select");
    pageSize.setAttribute("aria-label", "平台账户完整性每页条数");
    [20, 50, 100].forEach((value) => {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = `${value}行/页`;
      option.selected = value === selectedPlatformBalancePageSize;
      pageSize.append(option);
    });
    pageSize.addEventListener("change", () => {
      selectedPlatformBalancePageSize = Number(pageSize.value);
      openPlatformBalanceResults(status, 1);
    });
    toolbar.append(filters, pageSize);
    elements.reconciliationBrowser.append(toolbar);

    const detailHost = document.createElement("div");
    detailHost.className = "platform-balance-detail-host";
    elements.reconciliationBrowser.append(detailHost);
    const scroller = document.createElement("div");
    scroller.className = "platform-balance-table-scroll";
    const table = document.createElement("table");
    table.className = "platform-balance-table";
    table.innerHTML = `
      <thead><tr>
        <th>结论</th><th>层级</th><th>测试批次</th><th>账户</th><th>日期/月</th>
        <th>汇总笔数</th><th>逐笔笔数</th><th>汇总收入</th><th>逐笔收入</th>
        <th>汇总支出</th><th>逐笔支出</th><th>期末余额</th><th>公式期末</th>
        <th>主要差异</th><th>原因与下一步</th><th>来源</th>
      </tr></thead>`;
    const body = document.createElement("tbody");
    data.rows.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span class="balance-status ${escapeHtml(row.status)}">${escapeHtml(row.statusLabel)}</span></td>
        <td>${escapeHtml(row.levelLabel)}</td>
        <td>${escapeHtml(row.batchKey || "—")}</td>
        <td>${escapeHtml(row.account || "—")}</td>
        <td>${escapeHtml(row.periodKey || "—")}</td>
        <td>${formatOptionalCount(row.summaryCount)}</td>
        <td>${formatOptionalCount(row.detailCount)}</td>
        <td>${formatOptionalMoney(row.summaryIncomeCents)}</td>
        <td>${formatOptionalMoney(row.detailIncomeCents)}</td>
        <td>${formatOptionalMoney(row.summaryExpenseCents)}</td>
        <td>${formatOptionalMoney(row.detailExpenseCents)}</td>
        <td>${formatOptionalMoney(row.closingBalanceCents)}</td>
        <td>${formatOptionalMoney(row.calculatedClosingBalanceCents)}</td>
        <td>${formatOptionalMoney(row.differenceCents)}</td>
        <td class="balance-explanation"><strong>${escapeHtml(row.explanation)}</strong><span>${escapeHtml(row.suggestion)}</span></td>`;
      const source = document.createElement("td");
      const sourceButton = document.createElement("button");
      sourceButton.type = "button";
      sourceButton.className = "text-button";
      sourceButton.textContent = `${row.source.sheetName}${row.source.rowNumber}行`;
      sourceButton.addEventListener("click", () => renderPlatformBalanceSource(row, detailHost));
      source.append(sourceButton);
      tr.append(source);
      body.append(tr);
    });
    table.append(body);
    scroller.append(table);
    elements.reconciliationBrowser.append(scroller);

    const pager = document.createElement("div");
    pager.className = "pager";
    const info = document.createElement("span");
    info.textContent = `第${data.pagination.page}/${data.pagination.totalPages}页 · 当前${data.pagination.fromRow}—${data.pagination.toRow}行`;
    const actions = document.createElement("div");
    [["上一页", data.pagination.page - 1], ["下一页", data.pagination.page + 1]].forEach(([label, target]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button compact-button";
      button.textContent = label;
      button.disabled = target < 1 || target > data.pagination.totalPages;
      button.addEventListener("click", () => openPlatformBalanceResults(status, target));
      actions.append(button);
    });
    pager.append(info, actions);
    elements.reconciliationBrowser.append(pager);
  } catch (error) {
    elements.reconciliationBrowser.innerHTML = `<div class="state-box compact error"><strong>平台账户完整性读取失败</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

function renderPlatformBalanceSource(row, host) {
  host.innerHTML = "";
  const card = document.createElement("article");
  card.className = "platform-balance-source-card";
  const title = document.createElement("div");
  title.innerHTML = `<strong>${escapeHtml(row.source.sheetName)} · Excel第${row.source.rowNumber}行</strong><span>${escapeHtml(row.statusLabel)}</span>`;
  const grid = document.createElement("div");
  Object.entries(row.source.values || {}).forEach(([label, value]) => {
    const item = document.createElement("div");
    item.innerHTML = `<span>${escapeHtml(label)}</span><b>${escapeHtml(String(value ?? "—"))}</b>`;
    grid.append(item);
  });
  card.append(title, grid);
  host.append(card);
}

async function openPendingSettlementResults(status = "all", page = 1) {
  selectedPendingSettlementFilter = status;
  elements.reconciliationBrowser.classList.remove("wide-reconciliation-browser");
  elements.reconciliationBrowser.innerHTML = "";
  const pendingSettlement = selectedTaskDetail && selectedTaskDetail.pendingSettlement;
  if (!pendingSettlement || !pendingSettlement.run) {
    const state = document.createElement("div");
    state.className = "state-box compact reconciliation-unavailable";
    state.innerHTML = "<strong>尚未导入待结算订单资料</strong><span>导入后会逐笔区分正常等待、逾期、售后、平台限制、资料不足和排除项。</span>";
    const action = document.createElement("button");
    action.type = "button";
    action.className = "primary-button inline-button";
    action.textContent = "去导入资料";
    action.addEventListener("click", () => switchView("import"));
    state.append(action);
    elements.reconciliationBrowser.append(state);
    return;
  }
  elements.reconciliationBrowser.innerHTML = '<div class="state-box compact">正在读取待结算分类……</div>';
  try {
    const data = await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/pending-settlement-results?status=${encodeURIComponent(status)}&page=${page}&pageSize=${selectedPendingSettlementPageSize}`
    );
    elements.reconciliationBrowser.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "reconciliation-heading platform-balance-heading";
    heading.innerHTML = `
      <div><h2>待结算订单跟踪</h2><p>先排除取消/退款和已结算，再按售后、冻结限制、预计时间与等待边界分类。</p></div>
      <span class="trial-badge">${escapeHtml(data.summary.mappingVersion)} · 试运行不阻断</span>`;
    elements.reconciliationBrowser.append(heading);

    const notice = document.createElement("div");
    notice.className = "trial-notice";
    notice.textContent = `${pendingSettlement.notice}本次模拟核对时点：${formatDateTime(data.summary.asOf)}。`;
    elements.reconciliationBrowser.append(notice);

    const metrics = document.createElement("div");
    metrics.className = "platform-balance-metrics pending-settlement-metrics";
    [
      ["待结算源数据", data.summary.pendingSourceCount],
      ["正常等待", data.summary.waitingCount],
      ["逾期未结算", data.summary.overdueCount],
      ["需跟踪", data.summary.attentionCount],
      ["已排除", data.summary.excludedCount],
      ["预计结算金额", formatMoney(data.summary.pendingAmountCents || 0)],
    ].forEach(([label, value]) => {
      const item = document.createElement("div");
      const display = typeof value === "number" ? value.toLocaleString("zh-CN") : value;
      item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(display)}</strong>`;
      metrics.append(item);
    });
    elements.reconciliationBrowser.append(metrics);

    const toolbar = document.createElement("div");
    toolbar.className = "platform-balance-toolbar";
    const filters = document.createElement("div");
    filters.className = "filter-pills";
    [
      ["all", `全部 ${data.summary.totalResultCount}`],
      ["attention", `需跟踪 ${data.summary.attentionCount}`],
      ["waiting", `正常等待 ${data.summary.waitingCount}`],
      ["overdue", `逾期 ${data.summary.overdueCount}`],
      ["excluded", `已排除 ${data.summary.excludedCount}`],
    ].forEach(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = key === status ? "selected" : "";
      button.textContent = label;
      button.addEventListener("click", () => openPendingSettlementResults(key, 1));
      filters.append(button);
    });
    const pageSize = document.createElement("select");
    pageSize.setAttribute("aria-label", "待结算跟踪每页条数");
    [20, 50, 100].forEach((value) => {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = `${value}行/页`;
      option.selected = value === selectedPendingSettlementPageSize;
      pageSize.append(option);
    });
    pageSize.addEventListener("change", () => {
      selectedPendingSettlementPageSize = Number(pageSize.value);
      openPendingSettlementResults(status, 1);
    });
    toolbar.append(filters, pageSize);
    elements.reconciliationBrowser.append(toolbar);

    const detailHost = document.createElement("div");
    detailHost.className = "platform-balance-detail-host pending-settlement-detail-host";
    elements.reconciliationBrowser.append(detailHost);
    const scroller = document.createElement("div");
    scroller.className = "platform-balance-table-scroll pending-settlement-table-scroll";
    const table = document.createElement("table");
    table.className = "platform-balance-table pending-settlement-table";
    table.innerHTML = `
      <thead><tr>
        <th>跟踪结论</th><th>场景</th><th>订单号</th><th>子订单号</th>
        <th>订单状态</th><th>结算状态</th><th>预计结算时间</th><th>预计结算金额</th>
        <th>订单完成时间</th><th>售后状态</th><th>限制/冻结</th><th>下次检查</th>
        <th>判断理由与下一步</th><th>完成条件</th><th>来源</th>
      </tr></thead>`;
    const body = document.createElement("tbody");
    data.rows.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span class="balance-status ${escapeHtml(row.status)}">${escapeHtml(row.statusLabel)}</span></td>
        <td>${escapeHtml(row.sceneCode || "—")}</td>
        <td>${escapeHtml(row.orderId || "—")}</td>
        <td>${escapeHtml(row.suborderId || "—")}</td>
        <td>${escapeHtml(row.orderStatus || "—")}</td>
        <td>${escapeHtml(row.settlementStatus || "—")}</td>
        <td>${escapeHtml(formatDateTime(row.expectedSettlementAt))}</td>
        <td>${formatOptionalMoney(row.expectedSettlementCents)}</td>
        <td>${escapeHtml(formatDateTime(row.completedAt))}</td>
        <td>${escapeHtml(row.afterSalesStatus || "—")}</td>
        <td>${escapeHtml(row.restrictionStatus || "—")}</td>
        <td>${escapeHtml(formatDateTime(row.recheckAt))}</td>
        <td class="balance-explanation"><strong>${escapeHtml(row.explanation)}</strong><span>${escapeHtml(row.suggestion)}</span></td>
        <td>${escapeHtml(row.completionCondition)}</td>`;
      const source = document.createElement("td");
      const sourceButton = document.createElement("button");
      sourceButton.type = "button";
      sourceButton.className = "text-button";
      sourceButton.textContent = row.auxiliarySource ? "查看2组源数据" : "查看源数据";
      sourceButton.addEventListener("click", () => renderPendingSettlementSources(row, detailHost));
      source.append(sourceButton);
      tr.append(source);
      body.append(tr);
    });
    table.append(body);
    scroller.append(table);
    elements.reconciliationBrowser.append(scroller);

    const pager = document.createElement("div");
    pager.className = "pager";
    const info = document.createElement("span");
    info.textContent = `第${data.pagination.page}/${data.pagination.totalPages}页 · 当前${data.pagination.fromRow}—${data.pagination.toRow}行`;
    const actions = document.createElement("div");
    [["上一页", data.pagination.page - 1], ["下一页", data.pagination.page + 1]].forEach(([label, target]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button compact-button";
      button.textContent = label;
      button.disabled = target < 1 || target > data.pagination.totalPages;
      button.addEventListener("click", () => openPendingSettlementResults(status, target));
      actions.append(button);
    });
    pager.append(info, actions);
    elements.reconciliationBrowser.append(pager);
  } catch (error) {
    elements.reconciliationBrowser.innerHTML = `<div class="state-box compact error"><strong>待结算跟踪读取失败</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

function renderPendingSettlementSources(row, host) {
  host.innerHTML = "";
  const toolbar = document.createElement("div");
  toolbar.className = "pending-source-toolbar";
  toolbar.innerHTML = `<strong>${escapeHtml(row.sceneCode)} · 分类依据</strong>`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "secondary-button compact-button";
  close.textContent = "关闭源数据";
  close.addEventListener("click", () => { host.innerHTML = ""; });
  toolbar.append(close);
  host.append(toolbar);
  [row.source, row.auxiliarySource].filter(Boolean).forEach((source, index) => {
    const card = document.createElement("article");
    card.className = "platform-balance-source-card";
    const title = document.createElement("div");
    title.innerHTML = `<strong>${escapeHtml(source.sheetName)} · Excel第${source.rowNumber}行</strong><span>${index === 0 ? "主要证据" : "售后/状态辅助证据"}</span>`;
    const grid = document.createElement("div");
    Object.entries(source.values || {}).forEach(([label, value]) => {
      const item = document.createElement("div");
      item.innerHTML = `<span>${escapeHtml(label)}</span><b>${escapeHtml(String(value ?? "—"))}</b>`;
      grid.append(item);
    });
    card.append(title, grid);
    host.append(card);
  });
}

function formatOptionalMoney(value) {
  return value === null || value === undefined ? "—" : formatMoney(value);
}

function formatOptionalCount(value) {
  return value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN");
}

function openWideScene(fileId, scene) {
  selectedWideScene = scene;
  selectedWideFilter = "all";
  selectedWideQuery = "";
  activateReconcileTab(fileId, wideReconciliationTab, 1);
}

async function openWideReconciliation(
  fileId, status = "all", scene = "all", query = "", page = 1
) {
  if (!selectedTaskId) return;
  selectedWideFilter = status;
  selectedWideScene = scene;
  selectedWideQuery = query;
  elements.reconciliationBrowser.innerHTML = '<div class="state-box compact table-loading">正在把订单、售后、结算、资金和成本整理到同一张表……</div>';
  try {
    const params = new URLSearchParams({
      status,
      scene,
      query,
      page: String(page),
      pageSize: String(selectedWidePageSize),
    });
    const result = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/wide-reconciliation-results?${params}`);
    renderWideReconciliation(result);
  } catch (error) {
    elements.reconciliationBrowser.innerHTML = `<div class="state-box error compact">对账宽表读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderWideReconciliation(result) {
  const browser = elements.reconciliationBrowser;
  browser.innerHTML = "";
  browser.classList.add("wide-reconciliation-browser");

  const heading = document.createElement("div");
  heading.className = "record-heading reconciliation-heading wide-heading";
  const title = document.createElement("div");
  title.innerHTML = "<h2>对账明细宽表</h2><p>一行一个子订单；多笔售后、结算和资金保留笔数，点击当前行即可展开证据。</p>";
  const controls = document.createElement("div");
  controls.className = "wide-heading-controls";

  const searchForm = document.createElement("form");
  searchForm.className = "wide-search";
  const searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.placeholder = "搜子订单、货号、售后或流水号";
  searchInput.value = result.query || "";
  searchInput.setAttribute("aria-label", "搜索对账明细");
  const searchButton = document.createElement("button");
  searchButton.type = "submit";
  searchButton.className = "secondary-button compact-button";
  searchButton.textContent = "搜索";
  searchForm.append(searchInput, searchButton);
  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    openWideReconciliation(result.fileId, result.filter, result.scene, searchInput.value.trim(), 1);
  });

  const sceneSelect = document.createElement("select");
  sceneSelect.className = "wide-scene-select";
  sceneSelect.setAttribute("aria-label", "筛选业务场景");
  [
    ["all", "全部场景"],
    ["ordinary_settlement", "普通结算"],
    ["refund_settlement", "退款结算"],
    ["cross_month", "订单与结算"],
    ["after_sale", "售后"],
    ["cost", "成本"],
    ["other_fund", "其他收支"],
    ["order_only", "仅订单资料"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = result.scene === value;
    sceneSelect.append(option);
  });
  sceneSelect.addEventListener("change", () => {
    openWideReconciliation(result.fileId, "all", sceneSelect.value, result.query, 1);
  });

  const pageSize = document.createElement("select");
  pageSize.className = "wide-page-size";
  pageSize.setAttribute("aria-label", "每页条数");
  [20, 50, 100].forEach((size) => {
    const option = document.createElement("option");
    option.value = String(size);
    option.textContent = `${size}行/页`;
    option.selected = size === result.pagination.pageSize;
    pageSize.append(option);
  });
  pageSize.addEventListener("change", () => {
    selectedWidePageSize = Number(pageSize.value);
    openWideReconciliation(result.fileId, result.filter, result.scene, result.query, 1);
  });
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "secondary-button compact-button export-button";
  exportButton.textContent = "导出当前范围";
  exportButton.title = `导出当前状态、场景和搜索条件下全部${result.pagination.totalRows.toLocaleString("zh-CN")}行，不受分页限制`;
  exportButton.addEventListener("click", () => downloadResultExport(result, exportButton));
  controls.append(searchForm, sceneSelect, pageSize, exportButton);
  heading.append(title, controls);
  browser.append(heading);

  const summary = document.createElement("div");
  summary.className = "wide-summary-strip";
  [
    ["当前范围", `${result.summary.totalRowCount.toLocaleString("zh-CN")}行`],
    ["待处理", `${result.summary.attentionCount.toLocaleString("zh-CN")}行`],
    ["核对一致", `${result.summary.matchedCount.toLocaleString("zh-CN")}行`],
    ["未进入结算", `${result.summary.noSettlementCount.toLocaleString("zh-CN")}行`],
    ["结算净额", formatMoney(result.summary.settlementNetTotalCents)],
    ["平台资金净变动", formatMoney(result.summary.fundNetTotalCents)],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
    summary.append(item);
  });
  browser.append(summary);

  const toolbar = document.createElement("div");
  toolbar.className = "reconciliation-toolbar wide-toolbar";
  const filters = [
    ["all", "全部", result.summary.totalRowCount],
    ["needs_attention", "待处理", result.summary.attentionCount],
    ["matched", "核对一致", result.summary.matchedCount],
    ["no_settlement", "未进入结算", result.summary.noSettlementCount],
    ["resolved", "人工已处理", result.summary.resolvedCount + result.summary.carriedForwardCount],
  ];
  filters.forEach(([value, label, count]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `filter-chip ${result.filter === value ? "selected" : ""}`;
    button.textContent = `${label} ${count.toLocaleString("zh-CN")}`;
    button.addEventListener("click", () => {
      openWideReconciliation(result.fileId, value, result.scene, result.query, 1);
    });
    toolbar.append(button);
  });
  const range = document.createElement("span");
  range.textContent = result.pagination.totalRows
    ? `当前第${result.pagination.fromRow.toLocaleString("zh-CN")}—${result.pagination.toRow.toLocaleString("zh-CN")}行`
    : "当前条件下没有数据";
  toolbar.append(range);
  browser.append(toolbar);

  const detailHost = document.createElement("div");
  detailHost.className = "reconciliation-detail-host wide-detail-host";
  detailHost.hidden = true;
  browser.append(detailHost);

  if (!result.rows.length) {
    const empty = document.createElement("div");
    empty.className = "state-box compact result-empty wide-empty";
    empty.innerHTML = "<strong>没有符合条件的对账明细</strong><span>可以清空搜索词或切换业务场景。</span>";
    browser.append(empty);
  } else {
    const scroll = document.createElement("div");
    scroll.className = "table-scroll reconciliation-table-scroll wide-table-scroll";
    const table = document.createElement("table");
    table.className = "reconciliation-table wide-table";
    const head = document.createElement("thead");
    const groupRow = document.createElement("tr");
    groupRow.className = "wide-group-row";
    wideColumnGroups.forEach((group) => {
      const th = document.createElement("th");
      th.colSpan = group.columns.length;
      th.className = group.className;
      th.textContent = group.label;
      groupRow.append(th);
    });
    const labelRow = document.createElement("tr");
    labelRow.className = "wide-label-row";
    const flatColumns = wideColumnGroups.flatMap((group) => group.columns);
    flatColumns.forEach((column, index) => {
      const th = document.createElement("th");
      th.textContent = column[1];
      th.classList.add(`wide-column-${column[0]}`);
      if (column[2] === "money") th.classList.add("cents");
      if (index < 4) th.classList.add("wide-sticky", `wide-sticky-${index + 1}`);
      labelRow.append(th);
    });
    head.append(groupRow, labelRow);
    table.append(head);

    const body = document.createElement("tbody");
    result.rows.forEach((row) => {
      const tr = document.createElement("tr");
      tr.className = `wide-data-row wide-row-${row.status}`;
      flatColumns.forEach((column, index) => {
        const td = document.createElement("td");
        td.classList.add(`wide-column-${column[0]}`);
        if (column[2] === "money") td.classList.add("cents");
        if (index < 4) td.classList.add("wide-sticky", `wide-sticky-${index + 1}`);
        fillWideCell(td, row, column, result.fileId, detailHost);
        tr.append(td);
      });
      body.append(tr);
    });
    table.append(body);
    scroll.append(table);
    browser.append(scroll);
  }

  const pager = document.createElement("div");
  pager.className = "pager wide-pager";
  const label = document.createElement("span");
  label.textContent = `第${result.pagination.page}/${result.pagination.totalPages}页`;
  const actions = document.createElement("div");
  [["上一页", result.pagination.page - 1, result.pagination.page <= 1], ["下一页", result.pagination.page + 1, result.pagination.page >= result.pagination.totalPages]].forEach(([text, page, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button compact-button";
    button.textContent = text;
    button.disabled = disabled;
    button.addEventListener("click", () => {
      openWideReconciliation(result.fileId, result.filter, result.scene, result.query, page);
    });
    actions.append(button);
  });
  pager.append(label, actions);
  browser.append(pager);
}

function fillWideCell(cell, row, column, fileId, detailHost) {
  const [key, , type] = column;
  if (type === "status") {
    const chip = document.createElement("span");
    chip.className = `result-status ${row.status}`;
    chip.textContent = row.statusLabel;
    cell.append(chip);
    return;
  }
  if (type === "action") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "table-link wide-evidence-button";
    button.textContent = row.resultCount ? `展开${row.resultCount}项` : "查看来源";
    button.addEventListener("click", () => renderWideEvidence(row, fileId, detailHost));
    cell.append(button);
    return;
  }
  let value = row[key];
  if (type === "money") value = value === null || value === undefined ? "—" : formatMoney(value);
  else if (type === "datetime") value = formatDateTime(value);
  else if (type === "list") value = formatWideList(value);
  else if (type === "sourceRows") value = formatWideSourceRows(value);
  else if (value === null || value === undefined || value === "") value = "—";
  else value = String(value);
  cell.textContent = value;
  cell.title = value;
  if (type === "longText") cell.classList.add("wide-long-text");
}

function formatWideList(values) {
  if (!Array.isArray(values) || !values.length) return "—";
  const visible = values.slice(0, 2).join("、");
  return values.length > 2 ? `${visible} 等${values.length}项` : visible;
}

function formatWideSourceRows(rows) {
  if (!Array.isArray(rows) || !rows.length) return "—";
  const grouped = new Map();
  rows.forEach((row) => {
    if (!grouped.has(row.sheetName)) grouped.set(row.sheetName, []);
    grouped.get(row.sheetName).push(row.rowNumber);
  });
  return [...grouped.entries()]
    .map(([sheet, numbers]) => `${sheet}${numbers.slice(0, 3).join("/")}${numbers.length > 3 ? `等${numbers.length}行` : ""}`)
    .join(" · ");
}

function renderWideEvidence(row, fileId, host) {
  host.hidden = false;
  host.innerHTML = "";
  const card = document.createElement("article");
  card.className = "reconciliation-detail-card wide-evidence-card";
  const header = document.createElement("div");
  header.className = "detail-card-header";
  const title = document.createElement("div");
  title.innerHTML = `<span class="result-status ${escapeHtml(row.status)}">${escapeHtml(row.statusLabel)}</span><h3>${escapeHtml(row.subOrderId ? `子订单 ${row.subOrderId}` : row.fundTransactionIds[0] ? `资金流水 ${row.fundTransactionIds[0]}` : "未关联资料")}</h3>`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "detail-close";
  close.setAttribute("aria-label", "关闭展开内容");
  close.textContent = "×";
  close.addEventListener("click", () => {
    host.hidden = true;
    host.innerHTML = "";
  });
  header.append(title, close);
  card.append(header);

  const explanation = document.createElement("div");
  explanation.className = "result-explanation";
  explanation.innerHTML = `<strong>当前结论</strong><span>${escapeHtml(row.reason)}</span><strong>下一步</strong><span>${escapeHtml(row.suggestion)}</span>`;
  card.append(explanation);

  const facts = document.createElement("div");
  facts.className = "wide-evidence-facts";
  [
    ["订单", row.subOrderId || "未关联", `应付${row.orderPayableCents == null ? "—" : formatMoney(row.orderPayableCents)} · 预计商家应收${row.expectedMerchantReceivableCents == null ? "—" : formatMoney(row.expectedMerchantReceivableCents)}`],
    ["售后", `${row.afterSaleCount}笔`, `申请退款${row.afterSaleRequestedRefundCents == null ? "—" : formatMoney(row.afterSaleRequestedRefundCents)} · 成功退款${row.afterSaleRefundCents == null ? "—" : formatMoney(row.afterSaleRefundCents)} · ${formatWideList(row.afterSaleStatuses)}`],
    ["结算", `${row.settlementCount}笔`, `收入${row.settlementIncomeCents == null ? "—" : formatMoney(row.settlementIncomeCents)} · 支出${row.settlementExpenseCents == null ? "—" : formatMoney(row.settlementExpenseCents)}`],
    ["平台资金", `${row.fundCount}笔`, `净额${row.fundNetCents == null ? "—" : formatMoney(row.fundNetCents)} · ${formatWideList(row.fundScenes)}`],
    ["静态成本", row.costStatus || "未关联", row.totalCostCents == null ? "当前没有可用成本" : `订单成本${formatMoney(row.totalCostCents)}`],
  ].forEach(([label, value, meta]) => {
    const item = document.createElement("article");
    item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(meta)}</small>`;
    facts.append(item);
  });
  card.append(facts);

  const sourceLine = document.createElement("p");
  sourceLine.className = "wide-source-line";
  sourceLine.textContent = `来源：${formatWideSourceRows(row.sourceRows)}`;
  card.append(sourceLine);

  if (row.results.length) {
    const results = document.createElement("div");
    results.className = "wide-result-list";
    row.results.forEach((result) => {
      const item = document.createElement("article");
      const copy = document.createElement("div");
      const status = document.createElement("span");
      status.className = `result-status ${result.status}`;
      status.textContent = result.manualResolution
        ? result.manualResolution.resolutionStateLabel
        : result.statusLabel;
      const text = document.createElement("div");
      text.innerHTML = `<strong>${escapeHtml(result.resultTypeLabel)}</strong><small>${escapeHtml(result.explanation || "—")}</small>`;
      copy.append(status, text);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button compact-button";
      button.textContent = result.isAttention ? "查看并处理" : "查看证据";
      button.addEventListener("click", () => openWideResultDetail(fileId, result, host));
      item.append(copy, button);
      results.append(item);
    });
    card.append(results);
  }
  host.append(card);
}

function openWideResultDetail(fileId, result, host) {
  if (result.resultType === "ordinary_settlement") {
    openReconciliationDetail(fileId, result.id, host);
  } else if (result.resultType === "refund_settlement") {
    openRefundReconciliationDetail(fileId, result.id, host);
  } else {
    openSupplementaryDetail(fileId, result.resultType, result.id, host);
  }
}

async function openOrdinaryReconciliation(fileId, status = "all", page = 1) {
  if (!selectedTaskId) return;
  selectedReconciliationFilter = status;
  elements.reconciliationBrowser.innerHTML = '<div class="state-box compact table-loading">正在读取普通结算核对结果……</div>';
  try {
    const query = new URLSearchParams({
      status,
      page: String(page),
      pageSize: String(selectedReconciliationPageSize),
    });
    const result = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/reconciliation-results?${query}`);
    renderOrdinaryReconciliationResults(result);
  } catch (error) {
    elements.reconciliationBrowser.innerHTML = "";
    const state = document.createElement("div");
    state.className = "state-box error compact";
    state.textContent = `对账结果读取失败：${error.message}`;
    elements.reconciliationBrowser.append(state);
  }
}

function renderOrdinaryReconciliationResults(result) {
  const browser = elements.reconciliationBrowser;
  const summary = result.summary;
  browser.innerHTML = "";

  const heading = document.createElement("div");
  heading.className = "record-heading reconciliation-heading";
  const title = document.createElement("div");
  const name = document.createElement("h2");
  name.textContent = "普通结算核对";
  const meta = document.createElement("p");
  meta.textContent = `结算单类型“${summary.settlementType}” ↔ 资金场景“${summary.fundScene}” · 子订单唯一匹配 · 金额容差 ${(summary.toleranceCents / 100).toFixed(2)}元`;
  title.append(name, meta);
  const pageSizeLabel = document.createElement("label");
  pageSizeLabel.className = "page-size";
  pageSizeLabel.textContent = "每页";
  const select = document.createElement("select");
  [20, 50, 100].forEach((size) => {
    const option = document.createElement("option");
    option.value = String(size);
    option.textContent = `${size}笔`;
    option.selected = size === result.pagination.pageSize;
    select.append(option);
  });
  select.addEventListener("change", () => {
    selectedReconciliationPageSize = Number(select.value);
    openOrdinaryReconciliation(result.fileId, result.filter, 1);
  });
  pageSizeLabel.append(select);
  heading.append(title, buildResultHeadingActions(result, pageSizeLabel));
  browser.append(heading);

  const summaryGrid = document.createElement("div");
  summaryGrid.className = "reconciliation-summary-grid";
  [
    ["应核对", `${summary.totalResultCount.toLocaleString("zh-CN")}笔`],
    ["核对一致", `${summary.matchedCount.toLocaleString("zh-CN")}笔`],
    ["待处理", `${summary.attentionCount.toLocaleString("zh-CN")}笔`],
    ["结算金额", formatMoney(summary.settlementAmountTotalCents)],
    ["已匹配资金", formatMoney(summary.matchedFundAmountTotalCents)],
    ["一致项净差额", formatMoney(summary.differenceTotalCents)],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    const span = document.createElement("span");
    span.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    item.append(span, strong);
    summaryGrid.append(item);
  });
  browser.append(summaryGrid);

  const toolbar = document.createElement("div");
  toolbar.className = "reconciliation-toolbar";
  const filters = [
    ["all", "全部", summary.totalResultCount],
    ["matched", "核对一致", summary.matchedCount],
    ["needs_attention", "待处理", summary.attentionCount],
  ];
  filters.forEach(([value, label, count]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `filter-chip ${result.filter === value ? "selected" : ""}`;
    button.textContent = `${label} ${count.toLocaleString("zh-CN")}`;
    button.addEventListener("click", () => openOrdinaryReconciliation(result.fileId, value, 1));
    toolbar.append(button);
  });
  const range = document.createElement("span");
  range.textContent = result.pagination.totalRows
    ? `当前第${result.pagination.fromRow.toLocaleString("zh-CN")}—${result.pagination.toRow.toLocaleString("zh-CN")}笔`
    : "当前筛选下没有记录";
  toolbar.append(range);
  browser.append(toolbar);

  const detailHost = document.createElement("div");
  detailHost.className = "reconciliation-detail-host";
  detailHost.hidden = true;
  browser.append(detailHost);

  if (!result.rows.length) {
    const empty = document.createElement("div");
    empty.className = "state-box compact result-empty";
    empty.innerHTML = "<strong>没有需要处理的普通结算</strong><span>当前筛选条件下没有对账记录。</span>";
    browser.append(empty);
  } else {
    const scroll = document.createElement("div");
    scroll.className = "table-scroll reconciliation-table-scroll";
    const table = document.createElement("table");
    table.className = "reconciliation-table";
    table.innerHTML = "<thead><tr><th>核对状态</th><th>子订单号</th><th>结算金额</th><th>资金金额</th><th>差额</th><th>原Excel行</th><th>资金流水号</th><th>操作</th></tr></thead>";
    const body = document.createElement("tbody");
    result.rows.forEach((row) => {
      const tr = document.createElement("tr");
      const statusCell = document.createElement("td");
      const chip = document.createElement("span");
      chip.className = `result-status ${row.status}`;
      chip.textContent = row.statusLabel;
      statusCell.append(chip);
      appendManualStatus(statusCell, row.manualResolution);
      const values = [
        row.subOrderId || "—",
        formatMoney(row.settlementAmountCents),
        row.fundAmountCents === null ? "—" : formatMoney(row.fundAmountCents),
        row.differenceCents === null ? "—" : formatMoney(row.differenceCents),
        `结算 ${row.settlementRowNumber} / 资金 ${row.fundRowNumber || "—"}`,
        row.fundTransactionId || "—",
      ];
      tr.append(statusCell);
      values.forEach((value, index) => {
        const td = document.createElement("td");
        td.textContent = value;
        if (index >= 1 && index <= 3) td.className = "cents";
        td.title = value;
        tr.append(td);
      });
      const actionCell = document.createElement("td");
      const action = document.createElement("button");
      action.type = "button";
      action.className = "table-link";
      action.textContent = "查看详情";
      action.addEventListener("click", () => openReconciliationDetail(result.fileId, row.id, detailHost));
      actionCell.append(action);
      tr.append(actionCell);
      body.append(tr);
    });
    table.append(body);
    scroll.append(table);
    browser.append(scroll);
  }

  const pager = document.createElement("div");
  pager.className = "pager";
  const pageLabel = document.createElement("span");
  pageLabel.textContent = `第${result.pagination.page}/${result.pagination.totalPages}页`;
  const actions = document.createElement("div");
  const previous = document.createElement("button");
  previous.type = "button";
  previous.className = "secondary-button compact-button";
  previous.textContent = "上一页";
  previous.disabled = result.pagination.page <= 1;
  previous.addEventListener("click", () => openOrdinaryReconciliation(result.fileId, result.filter, result.pagination.page - 1));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "secondary-button compact-button";
  next.textContent = "下一页";
  next.disabled = result.pagination.page >= result.pagination.totalPages;
  next.addEventListener("click", () => openOrdinaryReconciliation(result.fileId, result.filter, result.pagination.page + 1));
  actions.append(previous, next);
  pager.append(pageLabel, actions);
  browser.append(pager);
}

async function openRefundReconciliation(fileId, status = "all", page = 1) {
  if (!selectedTaskId) return;
  selectedReconciliationFilter = status;
  elements.reconciliationBrowser.innerHTML = '<div class="state-box compact table-loading">正在读取退款结算净额归组结果……</div>';
  try {
    const query = new URLSearchParams({
      status,
      page: String(page),
      pageSize: String(selectedReconciliationPageSize),
    });
    const result = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/refund-reconciliation-results?${query}`);
    renderRefundReconciliationResults(result);
  } catch (error) {
    elements.reconciliationBrowser.innerHTML = "";
    const state = document.createElement("div");
    state.className = "state-box error compact";
    state.textContent = `退款对账结果读取失败：${error.message}`;
    elements.reconciliationBrowser.append(state);
  }
}

function renderRefundReconciliationResults(result) {
  const browser = elements.reconciliationBrowser;
  const summary = result.summary;
  browser.innerHTML = "";

  const heading = document.createElement("div");
  heading.className = "record-heading reconciliation-heading";
  const title = document.createElement("div");
  const name = document.createElement("h2");
  name.textContent = "退款结算净额与构成";
  const meta = document.createElement("p");
  meta.textContent = `净额规则正式生效：同子订单 + 同售后编号，${formatDuration(summary.autoGroupSeconds)}内唯一净额自动通过；退款构成按外部课程公式试算，不阻断本期完成`;
  title.append(name, meta);
  const pageSizeLabel = document.createElement("label");
  pageSizeLabel.className = "page-size";
  pageSizeLabel.textContent = "每页";
  const select = document.createElement("select");
  [20, 50, 100].forEach((size) => {
    const option = document.createElement("option");
    option.value = String(size);
    option.textContent = `${size}笔`;
    option.selected = size === result.pagination.pageSize;
    select.append(option);
  });
  select.addEventListener("change", () => {
    selectedReconciliationPageSize = Number(select.value);
    openRefundReconciliation(result.fileId, result.filter, 1);
  });
  pageSizeLabel.append(select);
  heading.append(title, buildResultHeadingActions(result, pageSizeLabel));
  browser.append(heading);

  const summaryGrid = document.createElement("div");
  summaryGrid.className = "reconciliation-summary-grid";
  [
    ["应归组", `${summary.totalResultCount.toLocaleString("zh-CN")}笔`],
    ["核对一致", `${summary.matchedCount.toLocaleString("zh-CN")}笔`],
    ["待处理", `${summary.attentionCount.toLocaleString("zh-CN")}笔`],
    ["退款结算净额", formatMoney(summary.settlementAmountTotalCents)],
    ["已归组资金净额", formatMoney(summary.matchedFundAmountTotalCents)],
    ["一致项净差额", formatMoney(summary.differenceTotalCents)],
    ["构成一致（试算）", `${(summary.componentMatchedCount || 0).toLocaleString("zh-CN")}笔`],
    ["构成异常（试算）", `${(summary.componentMismatchCount || 0).toLocaleString("zh-CN")}笔`],
    ["部分核对/资料不足", `${((summary.componentLimitedCount || 0) + (summary.componentMissingEvidenceCount || 0)).toLocaleString("zh-CN")}笔`],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    const span = document.createElement("span");
    span.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    item.append(span, strong);
    summaryGrid.append(item);
  });
  browser.append(summaryGrid);

  const toolbar = document.createElement("div");
  toolbar.className = "reconciliation-toolbar";
  [
    ["all", "全部", summary.totalResultCount],
    ["matched", "核对一致", summary.matchedCount],
    ["needs_attention", "待处理", summary.attentionCount],
  ].forEach(([value, label, count]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `filter-chip ${result.filter === value ? "selected" : ""}`;
    button.textContent = `${label} ${count.toLocaleString("zh-CN")}`;
    button.addEventListener("click", () => openRefundReconciliation(result.fileId, value, 1));
    toolbar.append(button);
  });
  const range = document.createElement("span");
  range.textContent = result.pagination.totalRows
    ? `当前第${result.pagination.fromRow.toLocaleString("zh-CN")}—${result.pagination.toRow.toLocaleString("zh-CN")}笔`
    : "当前筛选下没有记录";
  toolbar.append(range);
  browser.append(toolbar);

  const detailHost = document.createElement("div");
  detailHost.className = "reconciliation-detail-host";
  detailHost.hidden = true;
  browser.append(detailHost);

  if (!result.rows.length) {
    const empty = document.createElement("div");
    empty.className = "state-box compact result-empty";
    empty.innerHTML = "<strong>没有需要处理的退款结算</strong><span>当前筛选条件下没有对账记录。</span>";
    browser.append(empty);
  } else {
    const scroll = document.createElement("div");
    scroll.className = "table-scroll reconciliation-table-scroll";
    const table = document.createElement("table");
    table.className = "reconciliation-table";
    table.innerHTML = "<thead><tr><th>净额状态</th><th>子订单号</th><th>售后编号</th><th>退款构成试算</th><th>结算净额</th><th>资金净额</th><th>差额</th><th>资金行数</th><th>最大时差</th><th>结算Excel行</th><th>操作</th></tr></thead>";
    const body = document.createElement("tbody");
    result.rows.forEach((row) => {
      const tr = document.createElement("tr");
      const statusCell = document.createElement("td");
      const chip = document.createElement("span");
      chip.className = `result-status ${row.status}`;
      chip.textContent = row.statusLabel;
      statusCell.append(chip);
      appendManualStatus(statusCell, row.manualResolution);
      tr.append(statusCell);
      const values = [
        row.subOrderId || "—",
        row.afterSaleId || "—",
        row.componentStatusLabel || "未试算",
        formatMoney(row.settlementAmountCents),
        row.fundNetAmountCents === null ? "—" : formatMoney(row.fundNetAmountCents),
        row.differenceCents === null ? "—" : formatMoney(row.differenceCents),
        `${row.selectedRecordCount || row.candidateCount || 0}行`,
        row.maxTimeDifferenceSeconds === null ? "—" : formatDuration(row.maxTimeDifferenceSeconds),
        `第${row.settlementRowNumber}行`,
      ];
      values.forEach((value, index) => {
        const td = document.createElement("td");
        td.textContent = value;
        if (index >= 3 && index <= 5) td.className = "cents";
        td.title = value;
        tr.append(td);
      });
      const actionCell = document.createElement("td");
      const action = document.createElement("button");
      action.type = "button";
      action.className = "table-link";
      action.textContent = "查看归组明细";
      action.addEventListener("click", () => openRefundReconciliationDetail(result.fileId, row.id, detailHost));
      actionCell.append(action);
      tr.append(actionCell);
      body.append(tr);
    });
    table.append(body);
    scroll.append(table);
    browser.append(scroll);
  }

  const pager = document.createElement("div");
  pager.className = "pager";
  const pageLabel = document.createElement("span");
  pageLabel.textContent = `第${result.pagination.page}/${result.pagination.totalPages}页`;
  const actions = document.createElement("div");
  const previous = document.createElement("button");
  previous.type = "button";
  previous.className = "secondary-button compact-button";
  previous.textContent = "上一页";
  previous.disabled = result.pagination.page <= 1;
  previous.addEventListener("click", () => openRefundReconciliation(result.fileId, result.filter, result.pagination.page - 1));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "secondary-button compact-button";
  next.textContent = "下一页";
  next.disabled = result.pagination.page >= result.pagination.totalPages;
  next.addEventListener("click", () => openRefundReconciliation(result.fileId, result.filter, result.pagination.page + 1));
  actions.append(previous, next);
  pager.append(pageLabel, actions);
  browser.append(pager);
}

async function openRefundReconciliationDetail(fileId, resultId, host) {
  host.hidden = false;
  host.innerHTML = '<div class="state-box compact">正在读取结算账单和资金账单原始行……</div>';
  try {
    const response = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/refund-reconciliation-results/${encodeURIComponent(resultId)}`);
    renderRefundReconciliationDetail(response.result, fileId, host);
    host.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    host.innerHTML = `<div class="state-box error compact">明细读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderRefundReconciliationDetail(result, fileId, host) {
  host.innerHTML = "";
  const card = document.createElement("article");
  card.className = "reconciliation-detail-card";
  const header = document.createElement("div");
  header.className = "detail-card-header";
  const title = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = `result-status ${result.status}`;
  eyebrow.textContent = result.statusLabel;
  const heading = document.createElement("h3");
  heading.textContent = `子订单 ${result.subOrderId || "—"} · 售后 ${result.afterSaleId || "待确认"}`;
  title.append(eyebrow, heading);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "detail-close";
  close.setAttribute("aria-label", "关闭详情");
  close.textContent = "×";
  close.addEventListener("click", () => {
    host.hidden = true;
    host.innerHTML = "";
  });
  header.append(title, close);
  card.append(header);

  const explanation = document.createElement("div");
  explanation.className = "result-explanation";
  const component = result.componentCheck || {};
  const componentDetail = component.status
    ? `${escapeHtml(component.statusLabel || result.componentStatusLabel || "未试算")}；售后退款 ${component.refundAmountCents === null || component.refundAmountCents === undefined ? "—" : formatMoney(component.refundAmountCents)}；预计追回平台补贴 ${component.expectedPlatformSubsidyRecaptureCents === null || component.expectedPlatformSubsidyRecaptureCents === undefined ? "—" : formatMoney(component.expectedPlatformSubsidyRecaptureCents)}；资金实际退用户 ${component.fundUserRefundCents === null || component.fundUserRefundCents === undefined ? "—" : formatMoney(component.fundUserRefundCents)}；资金实际追回平台补贴 ${component.fundPlatformSubsidyRecaptureCents === null || component.fundPlatformSubsidyRecaptureCents === undefined ? "—" : formatMoney(component.fundPlatformSubsidyRecaptureCents)}`
    : "未试算";
  explanation.innerHTML = `<strong>净额判断</strong><span>${escapeHtml(result.explanation)}</span><strong>净额构成</strong><span>结算 ${formatMoney(result.settlementAmountCents)} ↔ 资金 ${result.fundNetAmountCents === null ? "—" : formatMoney(result.fundNetAmountCents)}；最大时差 ${result.maxTimeDifferenceSeconds === null ? "—" : formatDuration(result.maxTimeDifferenceSeconds)}</span><strong>退款构成试算</strong><span>${componentDetail}</span><strong>试算说明</strong><span>${escapeHtml(component.explanation || "外部课程公式仅用于试运行，尚未作为抖店官方规则。")}</span><strong>处理建议</strong><span>${escapeHtml(component.suggestion || result.suggestion)}</span>`;
  card.append(explanation);

  const sources = document.createElement("div");
  sources.className = "source-record-grid refund-source-grid";
  sources.append(
    buildSourceRecordCard(
      "结算账单",
      result.settlementSource,
      ["结算单类型", "子订单号", "结算金额", "结算账户", "结算时间", "订单号"],
      () => activateReconcileTab(fileId, "结算账单", 1)
    )
  );
  result.fundSources.forEach((source, index) => {
    sources.append(
      buildSourceRecordCard(
        `资金账单·净额组 ${index + 1}`,
        source,
        ["动账场景", "售后编号", "动账方向", "动账金额", "动账时间", "动帐流水号"],
        () => activateReconcileTab(fileId, "资金账单", 1)
      )
    );
  });
  if (!result.fundSources.length) {
    const missing = document.createElement("article");
    missing.className = "source-record-card missing";
    const groupCount = result.candidateGroups ? result.candidateGroups.length : 0;
    missing.innerHTML = `<div><strong>资金账单候选组</strong><span>${groupCount}组</span></div><p>未自动选中资金组。候选组已保留，不会被当成已核对结果。</p>`;
    sources.append(missing);
  }
  card.append(sources);
  const manualPanel = buildManualResolutionPanel(result, fileId);
  if (manualPanel) card.append(manualPanel);
  host.append(card);
}

async function openSupplementaryResults(fileId, resultType, status = "all", page = 1) {
  if (!selectedTaskId) return;
  selectedSupplementaryFilter = status;
  const config = supplementaryConfigByType(resultType);
  elements.reconciliationBrowser.innerHTML = `<div class="state-box compact table-loading">正在读取${escapeHtml(config.title)}……</div>`;
  try {
    const query = new URLSearchParams({
      status,
      page: String(page),
      pageSize: String(selectedReconciliationPageSize),
    });
    const result = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/supplementary-results/${encodeURIComponent(resultType)}?${query}`);
    renderSupplementaryResults(result);
  } catch (error) {
    elements.reconciliationBrowser.innerHTML = `<div class="state-box error compact">结果读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderSupplementaryResults(result) {
  const browser = elements.reconciliationBrowser;
  const config = supplementaryConfigByType(result.resultType);
  const summary = result.summary;
  browser.innerHTML = "";

  const heading = document.createElement("div");
  heading.className = "record-heading reconciliation-heading";
  const title = document.createElement("div");
  title.innerHTML = `<h2>${escapeHtml(config.title)}</h2><p>${escapeHtml(config.meta)}</p>`;
  const pageSizeLabel = document.createElement("label");
  pageSizeLabel.className = "page-size";
  pageSizeLabel.textContent = "每页";
  const select = document.createElement("select");
  [20, 50, 100].forEach((size) => {
    const option = document.createElement("option");
    option.value = String(size);
    option.textContent = `${size}笔`;
    option.selected = size === result.pagination.pageSize;
    select.append(option);
  });
  select.addEventListener("change", () => {
    selectedReconciliationPageSize = Number(select.value);
    openSupplementaryResults(result.fileId, result.resultType, result.filter, 1);
  });
  pageSizeLabel.append(select);
  heading.append(title, buildResultHeadingActions(result, pageSizeLabel));
  browser.append(heading);

  const summaryGrid = document.createElement("div");
  summaryGrid.className = "reconciliation-summary-grid supplementary-summary-grid";
  config.summaryItems(summary).forEach(([label, value]) => {
    const item = document.createElement("div");
    item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
    summaryGrid.append(item);
  });
  browser.append(summaryGrid);

  if (config.notice) {
    const notice = document.createElement("div");
    notice.className = "supplementary-notice";
    notice.textContent = config.notice;
    browser.append(notice);
  }

  const toolbar = document.createElement("div");
  toolbar.className = "reconciliation-toolbar";
  const clearedCount = summary.totalResultCount - summary.attentionCount;
  [
    ["all", "全部", summary.totalResultCount],
    ["cleared", config.clearedLabel, clearedCount],
    ["needs_attention", "待处理", summary.attentionCount],
  ].forEach(([value, label, count]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `filter-chip ${result.filter === value ? "selected" : ""}`;
    button.textContent = `${label} ${count.toLocaleString("zh-CN")}`;
    button.addEventListener("click", () => openSupplementaryResults(result.fileId, result.resultType, value, 1));
    toolbar.append(button);
  });
  const range = document.createElement("span");
  range.textContent = result.pagination.totalRows
    ? `当前第${result.pagination.fromRow.toLocaleString("zh-CN")}—${result.pagination.toRow.toLocaleString("zh-CN")}笔`
    : "当前筛选下没有记录";
  toolbar.append(range);
  browser.append(toolbar);

  const detailHost = document.createElement("div");
  detailHost.className = "reconciliation-detail-host supplementary-detail-host";
  detailHost.hidden = true;
  browser.append(detailHost);

  if (!result.rows.length) {
    const empty = document.createElement("div");
    empty.className = "state-box compact result-empty";
    empty.innerHTML = `<strong>当前没有${escapeHtml(config.emptyLabel)}</strong><span>可以切换筛选条件查看其他结果。</span>`;
    browser.append(empty);
  } else {
    const scroll = document.createElement("div");
    scroll.className = "table-scroll reconciliation-table-scroll";
    const table = document.createElement("table");
    table.className = "reconciliation-table supplementary-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["处理状态", ...config.columns.map((item) => item.label), "操作"].forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      headRow.append(th);
    });
    head.append(headRow);
    const body = document.createElement("tbody");
    result.rows.forEach((row) => {
      const tr = document.createElement("tr");
      const statusCell = document.createElement("td");
      const chip = document.createElement("span");
      chip.className = `result-status ${row.status}`;
      chip.textContent = row.statusLabel;
      statusCell.append(chip);
      appendManualStatus(statusCell, row.manualResolution);
      tr.append(statusCell);
      config.columns.forEach((column) => {
        const td = document.createElement("td");
        const value = column.value(row);
        td.textContent = value;
        td.title = value;
        if (column.money) td.className = "cents";
        tr.append(td);
      });
      const actionCell = document.createElement("td");
      const action = document.createElement("button");
      action.type = "button";
      action.className = "table-link";
      action.textContent = "查看来源";
      action.addEventListener("click", () => openSupplementaryDetail(
        result.fileId, result.resultType, row.id, detailHost
      ));
      actionCell.append(action);
      tr.append(actionCell);
      body.append(tr);
    });
    table.append(head, body);
    scroll.append(table);
    browser.append(scroll);
  }

  const pager = document.createElement("div");
  pager.className = "pager";
  const pageLabel = document.createElement("span");
  pageLabel.textContent = `第${result.pagination.page}/${result.pagination.totalPages}页`;
  const actions = document.createElement("div");
  const previous = document.createElement("button");
  previous.type = "button";
  previous.className = "secondary-button compact-button";
  previous.textContent = "上一页";
  previous.disabled = result.pagination.page <= 1;
  previous.addEventListener("click", () => openSupplementaryResults(
    result.fileId, result.resultType, result.filter, result.pagination.page - 1
  ));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "secondary-button compact-button";
  next.textContent = "下一页";
  next.disabled = result.pagination.page >= result.pagination.totalPages;
  next.addEventListener("click", () => openSupplementaryResults(
    result.fileId, result.resultType, result.filter, result.pagination.page + 1
  ));
  actions.append(previous, next);
  pager.append(pageLabel, actions);
  browser.append(pager);
}

function supplementaryConfigByType(resultType) {
  const configs = {
    cross_month: {
      title: "订单与结算勾稽",
      meta: "已结算订单核对商家应收与结算收入；未进入结算的订单按状态、售后和等待期分类。",
      notice: "缺历史订单不等于平台少结；超过预计结算日且未全额退款的已完成订单需要处理。",
      clearedLabel: "勾稽已通过",
      emptyLabel: "订单与结算记录",
      summaryItems: (s) => [
        ["结算勾稽", `${(s.settlementResultCount || 0).toLocaleString("zh-CN")}笔`],
        ["应收一致", `${(s.receivableMatchedCount || 0).toLocaleString("zh-CN")}笔`],
        ["应收差异", `${(s.receivableMismatchCount || 0).toLocaleString("zh-CN")}笔`],
        ["未进入结算", `${(s.unsettledOrderCount || 0).toLocaleString("zh-CN")}笔`],
        ["可能未结算", `${(s.possiblyUnsettledCount || 0).toLocaleString("zh-CN")}笔`],
        ["缺历史订单", `${s.missingHistoricalOrderCount.toLocaleString("zh-CN")}笔`],
      ],
      columns: [
        { label: "子订单号", value: (r) => r.subOrderId || r.primaryIdentifier || "—" },
        { label: "订单状态", value: (r) => r.orderStatus || "—" },
        { label: "订单完成时间", value: (r) => formatDateTime(r.completedAt || r.orderTime) },
        { label: "预计结算时间", value: (r) => formatDateTime(r.expectedAt) },
        { label: "订单应收", value: (r) => formatMoney(r.expectedMerchantReceivableCents), money: true },
        { label: "结算收入", value: (r) => formatMoney(r.settlementIncomeCents), money: true },
        { label: "差额", value: (r) => formatMoney(r.receivableDifferenceCents), money: true },
        { label: "来源Excel行", value: (r) => `第${r.sourceRowNumber}行` },
      ],
    },
    after_sale: {
      title: "售后状态分类",
      meta: "退款成功、售后关闭和换货分别判断；同一订单多次售后按售后单号保留。",
      notice: "售后关闭和换货成功都不会被当成现金退款。",
      clearedLabel: "已识别",
      emptyLabel: "售后状态记录",
      summaryItems: (s) => [
        ["售后记录", `${s.totalResultCount.toLocaleString("zh-CN")}笔`],
        ["退款成功", `${s.refundSuccessCount.toLocaleString("zh-CN")}笔`],
        ["售后关闭", `${s.closedCount.toLocaleString("zh-CN")}笔`],
        ["换货成功", `${s.exchangeSuccessCount.toLocaleString("zh-CN")}笔`],
        ["多次售后订单", `${s.multipleAfterSaleOrderCount.toLocaleString("zh-CN")}个`],
        ["退款冲突", `${(s.refundConflictCount || 0).toLocaleString("zh-CN")}笔`],
        ["退款缺售后单", `${(s.refundMissingAfterSaleCount || 0).toLocaleString("zh-CN")}笔`],
        ["新状态", `${s.unknownCount.toLocaleString("zh-CN")}笔`],
      ],
      columns: [
        { label: "售后单号", value: (r) => r.afterSaleId || r.primaryIdentifier || "—" },
        { label: "子订单号", value: (r) => r.subOrderId || "—" },
        { label: "售后类型", value: (r) => r.afterSaleType || "—" },
        { label: "平台状态", value: (r) => r.sourceStatus || "—" },
        { label: "退商品金额", value: (r) => formatMoney(r.amountCents), money: true },
        { label: "同订单售后", value: (r) => `${r.sameOrderAfterSaleCount || 0}笔` },
        { label: "售后Excel行", value: (r) => `第${r.sourceRowNumber}行` },
      ],
    },
    cost: {
      title: "订单成本关联",
      meta: "按订单货号关联成本表型号；当前只能使用静态成本，不冒充历史期间成本。",
      notice: "静态成本仅用于当前练习测算。正式历史利润需要成本生效日期。",
      clearedLabel: "已关联",
      emptyLabel: "成本关联记录",
      summaryItems: (s) => [
        ["订单行", `${s.totalResultCount.toLocaleString("zh-CN")}行`],
        ["已关联", `${s.matchedCount.toLocaleString("zh-CN")}行`],
        ["缺货号", `${s.missingSkuCount.toLocaleString("zh-CN")}行`],
        ["缺成本", `${s.missingCostCount.toLocaleString("zh-CN")}行`],
        ["待处理", `${s.attentionCount.toLocaleString("zh-CN")}行`],
        ["静态成本合计", formatMoney(s.matchedStaticCostTotalCents)],
      ],
      columns: [
        { label: "子订单号", value: (r) => r.subOrderId || r.primaryIdentifier || "—" },
        { label: "货号", value: (r) => r.sku || "—" },
        { label: "数量", value: (r) => String(r.quantity ?? "—") },
        { label: "单位成本", value: (r) => r.unitCostCents === null ? "—" : formatMoney(r.unitCostCents), money: true },
        { label: "订单成本", value: (r) => r.totalCostCents === null ? "—" : formatMoney(r.totalCostCents), money: true },
        { label: "订单Excel行", value: (r) => `第${r.sourceRowNumber}行` },
        { label: "成本Excel行", value: (r) => r.linkedRowNumber ? `第${r.linkedRowNumber}行` : "待补" },
      ],
    },
    other_fund: {
      title: "其他平台收支",
      meta: "平台费用、消费者赔付和提现单独展示；不会并入普通结算差异。",
      notice: "提现只表示抖店平台账户转出，不代表企业银行已经到账。",
      clearedLabel: "已分类",
      emptyLabel: "其他平台收支",
      summaryItems: (s) => [
        ["其他收支", `${s.totalResultCount.toLocaleString("zh-CN")}笔`],
        ["月付贴息", `${(s.categoryCounts.monthly_interest || 0).toLocaleString("zh-CN")}笔 · ${formatMoney(s.categoryTotalsCents.monthly_interest || 0)}`],
        ["运费险类", `${(s.categoryCounts.shipping_insurance || 0).toLocaleString("zh-CN")}笔 · ${formatMoney(s.categoryTotalsCents.shipping_insurance || 0)}`],
        ["消费者赔付", `${(s.categoryCounts.consumer_compensation || 0).toLocaleString("zh-CN")}笔 · ${formatMoney(s.categoryTotalsCents.consumer_compensation || 0)}`],
        ["提现", `${(s.categoryCounts.withdrawal || 0).toLocaleString("zh-CN")}笔 · ${formatMoney(s.categoryTotalsCents.withdrawal || 0)}`],
        ["等待分类", `${s.attentionCount.toLocaleString("zh-CN")}笔`],
      ],
      columns: [
        { label: "分类", value: (r) => r.categoryLabel || "等待分类" },
        { label: "平台场景", value: (r) => r.scene || "场景为空" },
        { label: "计费类型", value: (r) => r.chargeType || "—" },
        { label: "金额", value: (r) => formatMoney(r.amountCents), money: true },
        { label: "动账时间", value: (r) => formatDateTime(r.eventTime) },
        { label: "资金Excel行", value: (r) => `第${r.sourceRowNumber}行` },
      ],
    },
  };
  return configs[resultType];
}

async function openSupplementaryDetail(fileId, resultType, resultId, host) {
  host.hidden = false;
  host.innerHTML = '<div class="state-box compact">正在读取来源行……</div>';
  try {
    const response = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/supplementary-results/${encodeURIComponent(resultType)}/${encodeURIComponent(resultId)}`);
    renderSupplementaryDetail(response.result, fileId, host);
  } catch (error) {
    host.innerHTML = `<div class="state-box error compact">明细读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderSupplementaryDetail(result, fileId, host) {
  host.innerHTML = "";
  const card = document.createElement("article");
  card.className = "reconciliation-detail-card";
  const header = document.createElement("div");
  header.className = "detail-card-header";
  const title = document.createElement("div");
  title.innerHTML = `<span class="result-status ${escapeHtml(result.status)}">${escapeHtml(result.statusLabel)}</span><h3>${escapeHtml(supplementaryDetailTitle(result))}</h3>`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "detail-close";
  close.setAttribute("aria-label", "关闭详情");
  close.textContent = "×";
  close.addEventListener("click", () => {
    host.hidden = true;
    host.innerHTML = "";
  });
  header.append(title, close);
  card.append(header);
  const explanation = document.createElement("div");
  explanation.className = "result-explanation";
  explanation.innerHTML = `<strong>系统判断</strong><span>${escapeHtml(result.explanation)}</span><strong>处理建议</strong><span>${escapeHtml(result.suggestion)}</span>`;
  card.append(explanation);

  const sources = document.createElement("div");
  sources.className = "source-record-grid supplementary-source-grid";
  supplementarySourceCards(result).forEach(({ title: cardTitle, source, fields }) => {
    if (source) {
      sources.append(buildSourceRecordCard(
        cardTitle,
        source,
        fields,
        () => openSupplementarySource(source)
      ));
    } else {
      const missing = document.createElement("article");
      missing.className = "source-record-card missing";
      missing.innerHTML = `<div><strong>${escapeHtml(cardTitle)}</strong><span>未找到</span></div><p>当前没有可穿透的来源行，请按处理建议补充资料。</p>`;
      sources.append(missing);
    }
  });
  card.append(sources);
  const manualPanel = buildManualResolutionPanel(result, fileId);
  if (manualPanel) card.append(manualPanel);
  host.append(card);
}

function supplementaryDetailTitle(result) {
  if (result.resultType === "cross_month") return `子订单 ${result.subOrderId || result.primaryIdentifier || "—"}`;
  if (result.resultType === "after_sale") return `售后 ${result.afterSaleId || result.primaryIdentifier || "—"}`;
  if (result.resultType === "cost") return `子订单 ${result.subOrderId || result.primaryIdentifier || "—"} · 货号 ${result.sku || "待补"}`;
  return `${result.categoryLabel || "其他收支"} · ${result.primaryIdentifier || "—"}`;
}

function supplementarySourceCards(result) {
  if (result.resultType === "cross_month") {
    if (result.recordKind === "unsettled_order") {
      return [
        { title: "订单明细", source: result.source, fields: ["子订单编号", "主订单编号", "订单状态", "订单应付金额", "订单完成时间", "取消原因"] },
      ];
    }
    return [
      { title: "结算账单", source: result.source, fields: ["结算单类型", "子订单号", "收入合计", "结算金额", "结算时间", "下单时间"] },
      { title: "订单明细", source: result.linkedSource, fields: ["子订单编号", "主订单编号", "订单应付金额", "平台实际承担优惠金额", "达人实际承担优惠金额", "订单状态"] },
    ];
  }
  if (result.resultType === "after_sale") {
    return [
      { title: "售后表", source: result.source, fields: ["售后单号", "商品单号", "售后类型", "售后状态", "退商品金额（元）", "售后申请时间"] },
    ];
  }
  if (result.resultType === "cost") {
    return [
      { title: "订单明细", source: result.source, fields: ["子订单编号", "货号", "商品数量", "订单应付金额", "订单提交时间"] },
      { title: "成本表（静态）", source: result.linkedSource, fields: ["型号", "成本价"] },
    ];
  }
  return [
    { title: "资金账单", source: result.source, fields: ["动帐流水号", "动账场景", "计费类型", "动账方向", "动账金额", "动账时间", "备注"] },
  ];
}

function appendManualStatus(container, resolution) {
  if (!resolution) return;
  const chip = document.createElement("span");
  chip.className = `manual-status ${resolution.resolutionState}`;
  chip.textContent = resolution.resolutionStateLabel;
  container.append(chip);
}

function buildManualResolutionPanel(result, fileId) {
  if (!attentionResultStatuses.has(result.status) && !result.manualResolution) return null;
  const readOnly = Boolean(selectedTaskDetail && selectedTaskDetail.task.status === "completed");
  const section = document.createElement("section");
  section.className = "manual-resolution-panel";

  const heading = document.createElement("div");
  heading.className = "manual-resolution-heading";
  heading.innerHTML = "<div><strong>人工处理</strong><span>保留系统原判断，人工结论和每次修改另行留痕。</span></div>";
  if (result.manualResolution) {
    const current = document.createElement("span");
    current.className = `manual-status ${result.manualResolution.resolutionState}`;
    current.textContent = result.manualResolution.resolutionStateLabel;
    heading.append(current);
  }
  section.append(heading);

  if (result.manualResolution) {
    section.append(buildManualResolutionSummary(result.manualResolution, "当前人工结论"));
  }

  if (readOnly) {
    const note = document.createElement("div");
    note.className = "read-only-note";
    note.textContent = "本期已完成，当前页面只读。如需修改，请点击顶部“重新打开”并填写原因。";
    section.append(note);
  } else {
    const form = document.createElement("form");
    form.className = "manual-resolution-form";
    form.noValidate = true;

    const actionLabel = document.createElement("label");
    actionLabel.textContent = "处理方式";
    const action = document.createElement("select");
    action.name = "actionType";
    action.required = true;
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "请选择，不会默认代替你确认";
    placeholder.selected = true;
    action.append(placeholder);
    const actions = [
      ["confirm", "线下核实后确认"],
      ["adjust_amount", "人工调整金额"],
      ["carry_forward", "带到下月跟进"],
    ];
    if (result.candidateOptions && result.candidateOptions.length) {
      actions.splice(1, 0, ["select_candidate", "从候选中选择"]);
    }
    actions.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      action.append(option);
    });
    actionLabel.append(action);

    const candidateLabel = document.createElement("label");
    candidateLabel.className = "conditional-field";
    candidateLabel.hidden = true;
    candidateLabel.textContent = "候选记录";
    const candidate = document.createElement("select");
    candidate.name = "selectedCandidateKey";
    const candidatePlaceholder = document.createElement("option");
    candidatePlaceholder.value = "";
    candidatePlaceholder.textContent = "请选择一条候选";
    candidate.append(candidatePlaceholder);
    (result.candidateOptions || []).forEach((item) => {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = item.label;
      candidate.append(option);
    });
    candidateLabel.append(candidate);

    const amountLabel = document.createElement("label");
    amountLabel.className = "conditional-field";
    amountLabel.hidden = true;
    amountLabel.textContent = "调整后金额（元）";
    const amount = document.createElement("input");
    amount.name = "adjustedAmount";
    amount.inputMode = "decimal";
    amount.placeholder = "必须手动输入，不默认0";
    amountLabel.append(amount);

    const dateLabel = document.createElement("label");
    dateLabel.className = "conditional-field";
    dateLabel.hidden = true;
    dateLabel.textContent = "预计处理日期";
    const followUpDate = document.createElement("input");
    followUpDate.name = "followUpDate";
    followUpDate.type = "date";
    dateLabel.append(followUpDate);

    const reasonLabel = document.createElement("label");
    reasonLabel.className = "manual-reason-field";
    reasonLabel.textContent = "处理原因";
    const reason = document.createElement("textarea");
    reason.name = "reason";
    reason.maxLength = 500;
    reason.rows = 2;
    reason.placeholder = "说明核实依据或调整原因，便于以后追溯";
    reason.required = true;
    reasonLabel.append(reason);

    const footer = document.createElement("div");
    footer.className = "manual-resolution-actions";
    const message = document.createElement("span");
    message.className = "form-message";
    message.setAttribute("role", "status");
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "primary-button compact-button";
    submit.textContent = "保存人工处理";
    footer.append(message, submit);

    const refreshConditionalFields = () => {
      candidateLabel.hidden = action.value !== "select_candidate";
      amountLabel.hidden = action.value !== "adjust_amount";
      dateLabel.hidden = action.value !== "carry_forward";
    };
    action.addEventListener("change", refreshConditionalFields);
    form.append(actionLabel, candidateLabel, amountLabel, dateLabel, reasonLabel, footer);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      message.textContent = "";
      message.classList.remove("error");
      if (!action.value) {
        message.classList.add("error");
        message.textContent = "请选择处理方式。";
        return;
      }
      const payload = { actionType: action.value, reason: reason.value.trim() };
      if (!payload.reason) {
        message.classList.add("error");
        message.textContent = "请填写处理原因。";
        return;
      }
      if (action.value === "select_candidate") {
        if (!candidate.value) {
          message.classList.add("error");
          message.textContent = "请选择一条候选记录。";
          return;
        }
        payload.selectedCandidateKey = candidate.value;
      } else if (action.value === "adjust_amount") {
        try {
          payload.adjustedAmountCents = parseYuanToCents(amount.value);
        } catch (error) {
          message.classList.add("error");
          message.textContent = error.message;
          return;
        }
      } else if (action.value === "carry_forward") {
        if (!followUpDate.value) {
          message.classList.add("error");
          message.textContent = "请选择预计处理日期。";
          return;
        }
        payload.followUpDate = followUpDate.value;
      }
      submit.disabled = true;
      submit.textContent = "正在保存……";
      try {
        await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/results/${encodeURIComponent(result.resultType)}/${encodeURIComponent(result.id)}/manual-resolution`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        message.textContent = "已保存，正在刷新待处理数量……";
        await loadTaskDetail(selectedTaskId, null);
      } catch (error) {
        submit.disabled = false;
        submit.textContent = "保存人工处理";
        message.classList.add("error");
        message.textContent = error.message;
      }
    });
    section.append(form);
  }

  if (result.manualHistory && result.manualHistory.length) {
    const history = document.createElement("details");
    history.className = "manual-history";
    const summary = document.createElement("summary");
    summary.textContent = `查看处理记录（${result.manualHistory.length}次）`;
    history.append(summary);
    const list = document.createElement("div");
    result.manualHistory.forEach((item, index) => {
      list.append(buildManualResolutionSummary(item, index === 0 ? "最新" : `历史 ${index + 1}`));
    });
    history.append(list);
    section.append(history);
  }
  return section;
}

function buildManualResolutionSummary(resolution, title) {
  const card = document.createElement("div");
  card.className = "manual-resolution-summary";
  const parts = [resolution.actionLabel];
  if (resolution.selectedCandidateKey) parts.push(`候选 ${resolution.selectedCandidateKey}`);
  if (resolution.adjustedAmountCents !== null) parts.push(`调整为 ${formatMoney(resolution.adjustedAmountCents)}`);
  if (resolution.followUpDate) parts.push(`跟进日期 ${resolution.followUpDate}`);
  card.innerHTML = `<strong>${escapeHtml(title)} · ${escapeHtml(parts.join(" · "))}</strong><span>${escapeHtml(resolution.reason)}</span><small>${escapeHtml(formatDateTime(resolution.createdAt))}</small>`;
  return card;
}

function parseYuanToCents(value) {
  const text = String(value || "").trim();
  if (!/^-?\d+(\.\d{1,2})?$/.test(text)) {
    throw new Error("金额请使用元，最多两位小数，不能留空。");
  }
  const negative = text.startsWith("-");
  const unsigned = negative ? text.slice(1) : text;
  const [yuan, fraction = ""] = unsigned.split(".");
  const cents = Number(yuan) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(cents)) throw new Error("金额超出支持范围。");
  return negative ? -cents : cents;
}

async function openSupplementarySource(source) {
  if (!source) return;
  if (source.taskId && source.taskId !== selectedTaskId) {
    await selectTask(source.taskId, "reconcile");
  }
  activateReconcileTab(source.fileId || selectedFileId, source.sheetName, 1);
}

function formatDateTime(value) {
  if (!value) return "—";
  return String(value).replace("T", " ").replace("Z", "").replace(/\+00:00$/, "");
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds >= 86400 && seconds % 86400 === 0) return `${seconds / 86400}天`;
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600}小时`;
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60}分钟`;
  if (seconds >= 60) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
  return `${seconds}秒`;
}

async function openReconciliationDetail(fileId, resultId, host) {
  host.hidden = false;
  host.innerHTML = '<div class="state-box compact">正在读取结算账单和资金账单原始行……</div>';
  try {
    const response = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/reconciliation-results/${encodeURIComponent(resultId)}`);
    renderReconciliationDetail(response.result, fileId, host);
    host.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    host.innerHTML = `<div class="state-box error compact">明细读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderReconciliationDetail(result, fileId, host) {
  host.innerHTML = "";
  const card = document.createElement("article");
  card.className = "reconciliation-detail-card";
  const header = document.createElement("div");
  header.className = "detail-card-header";
  const title = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = `result-status ${result.status}`;
  eyebrow.textContent = result.statusLabel;
  const heading = document.createElement("h3");
  heading.textContent = `子订单 ${result.subOrderId || "—"}`;
  title.append(eyebrow, heading);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "detail-close";
  close.setAttribute("aria-label", "关闭详情");
  close.textContent = "×";
  close.addEventListener("click", () => {
    host.hidden = true;
    host.innerHTML = "";
  });
  header.append(title, close);
  card.append(header);

  const explanation = document.createElement("div");
  explanation.className = "result-explanation";
  explanation.innerHTML = `<strong>系统判断</strong><span>${escapeHtml(result.explanation)}</span><strong>处理建议</strong><span>${escapeHtml(result.suggestion)}</span>`;
  card.append(explanation);

  const sources = document.createElement("div");
  sources.className = "source-record-grid";
  sources.append(
    buildSourceRecordCard(
      "结算账单",
      result.settlementSource,
      ["结算单类型", "子订单号", "结算金额", "结算账户", "结算时间", "订单号"],
      () => activateReconcileTab(fileId, "结算账单", 1)
    )
  );
  if (result.fundSource) {
    sources.append(
      buildSourceRecordCard(
        "资金账单",
        result.fundSource,
        ["动账场景", "子订单号", "动账金额", "动账方向", "动账账户", "动帐流水号", "动账时间"],
        () => activateReconcileTab(fileId, "资金账单", 1)
      )
    );
  } else {
    const missing = document.createElement("article");
    missing.className = "source-record-card missing";
    missing.innerHTML = "<div><strong>资金账单</strong><span>未匹配</span></div><p>没有可穿透的资金原始行；候选流水会保留在异常结果中。</p>";
    sources.append(missing);
  }
  card.append(sources);
  const manualPanel = buildManualResolutionPanel(result, fileId);
  if (manualPanel) card.append(manualPanel);
  host.append(card);
}

function buildSourceRecordCard(titleText, source, fields, onOpenSheet) {
  const card = document.createElement("article");
  card.className = "source-record-card";
  const header = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = titleText;
  const row = document.createElement("span");
  row.textContent = `Excel 第${source.rowNumber}行`;
  header.append(title, row);
  card.append(header);
  const list = document.createElement("dl");
  fields.forEach((field) => {
    const dt = document.createElement("dt");
    dt.textContent = field;
    const dd = document.createElement("dd");
    const value = source.values[field];
    dd.textContent = formatSourceRecordValue(source, field, value);
    list.append(dt, dd);
  });
  card.append(list);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button compact-button";
  button.textContent = `打开${titleText}底表`;
  button.addEventListener("click", onOpenSheet);
  card.append(button);
  return card;
}

function formatSourceRecordValue(source, field, value) {
  if (field.includes("时间") && source.eventTime) {
    return source.eventTime.replace("T", " ").replace("Z", "");
  }
  if (
    (field === "结算金额" || field === "动账金额")
    && source.amountCents !== null
    && source.amountCents !== undefined
  ) {
    return formatMoney(source.amountCents);
  }
  if (field === "子订单号") {
    return source.sheetName === "结算账单"
      ? source.primaryIdentifier || "—"
      : source.secondaryIdentifier || "—";
  }
  if (field === "动帐流水号") return source.primaryIdentifier || "—";
  if (field === "订单号") return source.secondaryIdentifier || "—";
  if (value === null || value === undefined || value === "") return "—";
  return String(value).replace(/^'/, "");
}

function formatAmountSummary(summary) {
  if (!summary) return "暂无金额口径";
  if (summary.minCents !== undefined) {
    return `${summary.label} ${formatMoney(summary.minCents)}—${formatMoney(summary.maxCents)}`;
  }
  if (summary.inflowCents !== undefined) {
    return `${summary.label} ${formatMoney(summary.valueCents)} · 入账 ${formatMoney(summary.inflowCents)} · 出账 ${formatMoney(summary.outflowCents)}`;
  }
  return `${summary.label} ${formatMoney(summary.valueCents)}`;
}

async function openSheet(fileId, sheetName, page = 1) {
  if (!selectedTaskId) return;
  elements.recordBrowser.innerHTML = '<div class="state-box compact table-loading">正在读取底表数据……</div>';
  try {
    const query = new URLSearchParams({ sheet: sheetName, page: String(page), pageSize: String(selectedPageSize) });
    const result = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files/${encodeURIComponent(fileId)}/records?${query}`);
    renderRecordTable(result);
  } catch (error) {
    elements.recordBrowser.innerHTML = "";
    const state = document.createElement("div");
    state.className = "state-box error compact";
    state.textContent = `底表读取失败：${error.message}`;
    elements.recordBrowser.append(state);
  }
}

function renderRecordTable(result) {
  const browser = elements.recordBrowser;
  browser.innerHTML = "";
  const heading = document.createElement("div");
  heading.className = "record-heading";
  const title = document.createElement("div");
  const name = document.createElement("h2");
  name.textContent = result.sheetName;
  const meta = document.createElement("p");
  meta.textContent = `共${result.pagination.totalRows.toLocaleString("zh-CN")}行 · 当前第${result.pagination.fromRow.toLocaleString("zh-CN")}—${result.pagination.toRow.toLocaleString("zh-CN")}行 · 保留原Excel行号`;
  title.append(name, meta);

  const controls = document.createElement("div");
  controls.className = "table-controls";
  const privacy = document.createElement("span");
  privacy.textContent = "仅展示对账必要字段";
  const pageSizeLabel = document.createElement("label");
  pageSizeLabel.className = "page-size";
  pageSizeLabel.textContent = "每页";
  const select = document.createElement("select");
  [20, 50, 100].forEach((size) => {
    const option = document.createElement("option");
    option.value = String(size);
    option.textContent = `${size}行`;
    option.selected = size === result.pagination.pageSize;
    select.append(option);
  });
  select.addEventListener("change", () => {
    selectedPageSize = Number(select.value);
    openSheet(result.fileId, result.sheetName, 1);
  });
  pageSizeLabel.append(select);
  controls.append(privacy, pageSizeLabel);
  heading.append(title, controls);
  browser.append(heading);

  const scroll = document.createElement("div");
  scroll.className = "table-scroll";
  const table = document.createElement("table");
  const header = document.createElement("thead");
  const headerRow = document.createElement("tr");
  result.columns.forEach((column) => {
    const cell = document.createElement("th");
    cell.textContent = column.label;
    cell.className = column.type;
    headerRow.append(cell);
  });
  header.append(headerRow);
  const body = document.createElement("tbody");
  result.rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    result.columns.forEach((column) => {
      const cell = document.createElement("td");
      cell.className = column.type;
      cell.textContent = formatRecordValue(row.values[column.key], column.type);
      cell.title = cell.textContent;
      tableRow.append(cell);
    });
    body.append(tableRow);
  });
  table.append(header, body);
  scroll.append(table);
  browser.append(scroll);

  const pager = document.createElement("div");
  pager.className = "pager";
  const range = document.createElement("span");
  range.textContent = `第${result.pagination.page}/${result.pagination.totalPages}页`;
  const actions = document.createElement("div");
  const previous = document.createElement("button");
  previous.type = "button";
  previous.className = "secondary-button compact-button";
  previous.textContent = "上一页";
  previous.disabled = result.pagination.page <= 1;
  previous.addEventListener("click", () => openSheet(result.fileId, result.sheetName, result.pagination.page - 1));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "secondary-button compact-button";
  next.textContent = "下一页";
  next.disabled = result.pagination.page >= result.pagination.totalPages;
  next.addEventListener("click", () => openSheet(result.fileId, result.sheetName, result.pagination.page + 1));
  actions.append(previous, next);
  pager.append(range, actions);
  browser.append(pager);
}

function formatRecordValue(value, type) {
  if (value === null || value === undefined || value === "") return "—";
  if (type === "cents") return formatMoney(value);
  if (type === "money") {
    const numeric = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(numeric) ? formatMoney(Math.round(numeric * 100)) : String(value);
  }
  if (type === "datetime") return String(value).replace("T", " ");
  return String(value);
}

function renderAmountChecks(amountChecks, container) {
  if (!amountChecks) return;
  const section = document.createElement("section");
  section.className = "overview-section amount-check-result";
  const heading = document.createElement("div");
  heading.className = "overview-section-heading";
  const text = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = amountChecks.status === "passed" ? "内部金额检查全部通过" : "内部金额存在差异";
  const summary = document.createElement("p");
  summary.textContent = `${amountChecks.passedCount.toLocaleString("zh-CN")}/${amountChecks.totalCheckCount.toLocaleString("zh-CN")}次通过 · 容差${(amountChecks.toleranceCents / 100).toFixed(2)}元`;
  text.append(title, summary);
  const state = document.createElement("span");
  state.className = `data-state ${amountChecks.status}`;
  state.textContent = amountChecks.status === "passed" ? "全部通过" : `${amountChecks.failedCount + amountChecks.notCalculableCount}次需处理`;
  heading.append(text, state);
  section.append(heading);

  const cards = document.createElement("div");
  cards.className = "amount-check-grid";
  amountChecks.checkSummaries.forEach((check) => {
    const card = document.createElement("article");
    const top = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = check.checkLabel;
    const status = document.createElement("span");
    status.textContent = check.failedCount || check.notCalculableCount ? "有差异" : "通过";
    top.append(name, status);
    const count = document.createElement("b");
    count.textContent = `${check.passedCount.toLocaleString("zh-CN")}/${check.totalCount.toLocaleString("zh-CN")}`;
    const total = document.createElement("small");
    total.textContent = `平台金额 ${formatMoney(check.sourceAmountTotalCents)} · 差额 ${formatMoney(check.differenceTotalCents)}`;
    card.append(top, count, total);
    cards.append(card);
  });
  section.append(cards);
  container.append(section);
}

function renderIssueGroups(dataImport, container, headingText, file = null) {
  if (!dataImport || !dataImport.issueGroups || !dataImport.issueGroups.length) return;
  const section = document.createElement("section");
  section.className = "issue-section";
  const heading = document.createElement("div");
  heading.className = "overview-section-heading";
  const text = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = headingText;
  const meta = document.createElement("p");
  meta.textContent = `共${dataImport.blockingIssueCount}个阻断、${dataImport.warningIssueCount}个提醒，保留原Excel行号便于追溯。`;
  text.append(title, meta);
  heading.append(text);
  section.append(heading);

  const issues = document.createElement("div");
  issues.className = "issue-groups";
  dataImport.issueGroups.forEach((issue) => {
    const item = document.createElement("article");
    item.className = `issue-group ${issue.severity}`;
    const top = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = `${issue.sheetName} · ${issue.fieldName || "整张表"}`;
    const count = document.createElement("span");
    count.textContent = `${issue.count}条`;
    top.append(label, count);
    const message = document.createElement("p");
    message.textContent = issue.message;
    const source = document.createElement("small");
    source.textContent = issue.exampleRows.length
      ? `Excel第${issue.exampleRows.join("、")}行${issue.count > issue.exampleRows.length ? "等" : ""} · ${issue.suggestion}`
      : `整张表 · ${issue.suggestion}`;
    item.append(top, message, source);
    if (issue.code === "task_period_mismatch") {
      const targetPeriod = (issue.rawValues || []).find((value) => /^\d{4}-\d{2}$/.test(value));
      if (targetPeriod && file) {
        const correction = document.createElement("div");
        correction.className = "issue-correction";
        const explanation = document.createElement("span");
        explanation.textContent = `系统识别文件月份为 ${targetPeriod}。可直接生成修正任务并重新检查。`;
        correction.append(explanation, createPeriodCorrectionButton(targetPeriod));
        item.append(correction);
      }
    }
    issues.append(item);
  });
  section.append(issues);
  container.append(section);
}

function getTaskPeriodMismatch(dataImport) {
  if (!dataImport || !Array.isArray(dataImport.issueGroups)) return null;
  const issue = dataImport.issueGroups.find((item) => item.code === "task_period_mismatch");
  if (!issue) return null;
  const targetPeriod = (issue.rawValues || []).find((value) => /^\d{4}-\d{2}$/.test(value));
  return targetPeriod ? { issue, targetPeriod } : null;
}

function createPeriodCorrectionButton(targetPeriod) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "primary-button compact-button correction-button";
  button.textContent = `按 ${targetPeriod} 修正并重新检查`;
  button.addEventListener("click", () => correctTaskPeriod(targetPeriod, button));
  return button;
}

async function correctTaskPeriod(targetPeriod, button) {
  if (!selectedTaskId) return;
  const sourceTaskId = selectedTaskId;
  button.disabled = true;
  button.textContent = "正在生成修正任务……";
  try {
    const result = await request(`/api/tasks/${encodeURIComponent(sourceTaskId)}/correct-period`, {
      method: "POST",
      body: JSON.stringify({ targetPeriod }),
    });
    await loadTasks(false);
    await selectTask(result.task.id, "reconcile");
  } catch (error) {
    if (error.payload && error.payload.existingTask) {
      await loadTasks(false);
      await selectTask(error.payload.existingTask.id, "auto");
      return;
    }
    button.disabled = false;
    button.textContent = `按 ${targetPeriod} 修正并重新检查`;
    const message = document.createElement("span");
    message.className = "inline-error";
    message.textContent = error.message;
    button.insertAdjacentElement("afterend", message);
  }
}

function closeLifecycleDialog() {
  const overlay = document.querySelector(".modal-backdrop");
  if (overlay) overlay.remove();
  document.body.classList.remove("modal-open");
}

async function openTaskLifecycleDialog() {
  if (!selectedTaskId || !selectedTaskDetail) return;
  closeLifecycleDialog();
  const overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeLifecycleDialog();
  });
  const dialog = document.createElement("section");
  dialog.className = "lifecycle-dialog";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "本期状态");
  dialog.innerHTML = '<div class="state-box compact lifecycle-loading">正在核对完成条件……</div>';
  overlay.append(dialog);
  document.body.append(overlay);
  document.body.classList.add("modal-open");
  try {
    const task = selectedTaskDetail.task;
    const response = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/completion`);
    renderLifecycleDialog(dialog, task, response.completion);
  } catch (error) {
    dialog.innerHTML = `<div class="dialog-header"><div><h2>本期状态</h2><p>暂时无法读取</p></div><button type="button" class="detail-close" aria-label="关闭">×</button></div><p class="dialog-error">${escapeHtml(error.message)}</p>`;
    dialog.querySelector(".detail-close").addEventListener("click", closeLifecycleDialog);
  }
}

function renderLifecycleDialog(dialog, task, completion) {
  dialog.innerHTML = "";
  const header = document.createElement("div");
  header.className = "dialog-header";
  const title = document.createElement("div");
  const heading = document.createElement("h2");
  heading.textContent = task.status === "completed" ? "重新打开本期" : "完成本期";
  const meta = document.createElement("p");
  meta.textContent = `${task.period} · ${task.storeName} · 规则 ${completion.ruleVersionLabel}`;
  title.append(heading, meta);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "detail-close";
  close.setAttribute("aria-label", "关闭");
  close.textContent = "×";
  close.addEventListener("click", closeLifecycleDialog);
  header.append(title, close);
  dialog.append(header);

  const grid = document.createElement("div");
  grid.className = "completion-summary-grid";
  [
    ["处理链路", completion.processingReady ? "已运行" : "未完成", completion.processingReady],
    ["数据阻断", `${completion.blockingIssueCount}个`, completion.blockingIssueCount === 0],
    ["人工已处理", `${completion.resolvedCount}笔`, true],
    ["带到下月", `${completion.carriedForwardCount}笔`, true],
    ["仍未处理", `${completion.unresolvedCount}笔`, completion.unresolvedCount === 0],
  ].forEach(([label, value, passed]) => {
    const item = document.createElement("div");
    item.className = passed ? "passed" : "blocked";
    item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
    grid.append(item);
  });
  dialog.append(grid);

  if (task.status === "completed") {
    const note = document.createElement("div");
    note.className = "lifecycle-notice completed";
    note.textContent = "已完成期间为只读状态。重新打开不会删除上次完成记录，但必须说明原因。";
    dialog.append(note);
    const form = document.createElement("form");
    form.className = "lifecycle-form";
    const label = document.createElement("label");
    label.textContent = "重新打开原因";
    const reason = document.createElement("textarea");
    reason.rows = 3;
    reason.maxLength = 500;
    reason.placeholder = "例如：平台补发账单，需重新核对";
    label.append(reason);
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const message = document.createElement("span");
    message.className = "form-message";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary-button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", closeLifecycleDialog);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "primary-button";
    submit.textContent = "确认重新打开";
    actions.append(message, cancel, submit);
    form.append(label, actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const value = reason.value.trim();
      if (!value) {
        message.classList.add("error");
        message.textContent = "请填写重新打开原因。";
        return;
      }
      submit.disabled = true;
      submit.textContent = "正在打开……";
      try {
        await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/reopen`, {
          method: "POST",
          body: JSON.stringify({ reason: value }),
        });
        closeLifecycleDialog();
        await loadTasks(false);
        await loadTaskDetail(selectedTaskId, null);
      } catch (error) {
        submit.disabled = false;
        submit.textContent = "确认重新打开";
        message.classList.add("error");
        message.textContent = error.message;
      }
    });
    dialog.append(form);
    return;
  }

  const notice = document.createElement("div");
  notice.className = `lifecycle-notice ${completion.canComplete ? "ready" : "blocked"}`;
  notice.textContent = completion.canComplete
    ? "完成条件已满足。确认后本期进入只读，系统保留当前规则版本、人工处理和汇总快照。"
    : completion.unresolvedCount
      ? `还有${completion.unresolvedCount}笔必须处理的结果，暂时不能完成本期。`
      : "导入、金额检查或对账链路尚未完成，暂时不能完成本期。";
  dialog.append(notice);

  if (completion.unresolvedPreview && completion.unresolvedPreview.length) {
    const preview = document.createElement("div");
    preview.className = "unresolved-preview";
    const previewTitle = document.createElement("strong");
    previewTitle.textContent = "待处理预览";
    preview.append(previewTitle);
    completion.unresolvedPreview.slice(0, 5).forEach((item) => {
      const row = document.createElement("span");
      row.textContent = `${manualResultTypeLabel(item.resultType)} · ${item.primaryIdentifier || "未知编号"} · ${item.systemStatus}`;
      preview.append(row);
    });
    dialog.append(preview);
  }

  const form = document.createElement("form");
  form.className = "lifecycle-form";
  const label = document.createElement("label");
  label.textContent = "完成说明（可选）";
  const note = document.createElement("textarea");
  note.rows = 2;
  note.maxLength = 500;
  note.placeholder = "可记录本期特殊情况";
  label.append(note);
  const actions = document.createElement("div");
  actions.className = "dialog-actions";
  const message = document.createElement("span");
  message.className = "form-message";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "secondary-button";
  cancel.textContent = "取消";
  cancel.addEventListener("click", closeLifecycleDialog);
  if (!completion.canComplete) {
    const go = document.createElement("button");
    go.type = "button";
    go.className = "primary-button";
    go.textContent = completion.unresolvedCount ? "去处理待办" : "去检查导入";
    go.addEventListener("click", () => {
      closeLifecycleDialog();
      if (completion.unresolvedCount) openFirstUnresolved(completion.unresolvedPreview[0]);
      else switchView("import");
    });
    actions.append(message, cancel, go);
  } else {
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "primary-button";
    submit.textContent = "确认完成本期";
    actions.append(message, cancel, submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      submit.textContent = "正在完成……";
      try {
        await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/complete`, {
          method: "POST",
          body: JSON.stringify({ confirmed: true, note: note.value.trim() || null }),
        });
        closeLifecycleDialog();
        await loadTasks(false);
        await loadTaskDetail(selectedTaskId, null);
      } catch (error) {
        submit.disabled = false;
        submit.textContent = "确认完成本期";
        message.classList.add("error");
        message.textContent = error.message;
      }
    });
  }
  form.append(label, actions);
  dialog.append(form);
}

function manualResultTypeLabel(resultType) {
  return {
    ordinary_settlement: "普通结算",
    refund_settlement: "退款结算",
    cross_month: "订单与结算",
    after_sale: "售后状态",
    cost: "成本关联",
    other_fund: "其他收支",
  }[resultType] || resultType;
}

function openFirstUnresolved(item) {
  if (!item || !selectedFileId) return;
  switchView("reconcile");
  if (item.resultType === "ordinary_settlement") {
    selectedReconciliationFilter = "needs_attention";
    activateReconcileTab(selectedFileId, ordinaryReconciliationTab, 1);
    return;
  }
  if (item.resultType === "refund_settlement") {
    selectedReconciliationFilter = "needs_attention";
    activateReconcileTab(selectedFileId, refundReconciliationTab, 1);
    return;
  }
  const tab = Object.entries(supplementaryResultTabs).find(([, config]) => config.resultType === item.resultType);
  if (tab) {
    selectedSupplementaryFilter = "needs_attention";
    activateReconcileTab(selectedFileId, tab[0], 1);
  }
}

function formatMoney(cents) {
  const value = Number(cents || 0) / 100;
  return `${value < 0 ? "-" : ""}¥${Math.abs(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function prototypeEntityName(value) {
  return String(value ?? "");
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

async function loadSample() {
  const button = elements.loadSampleButton;
  button.disabled = true;
  button.textContent = "正在载入样例……";
  try {
    const result = await request("/api/sample/load", { method: "POST" });
    await loadTasks(false);
    await selectTask(result.task.id, "auto");
  } catch (error) {
    showTaskState(elements.taskError);
  } finally {
    button.disabled = false;
    button.textContent = "载入样例数据";
  }
}

async function submitWorkbook(event) {
  event.preventDefault();
  if (!selectedTaskId) return;
  const fileInput = elements.uploadForm.elements.workbook;
  const file = fileInput.files[0];
  elements.uploadMessage.textContent = "";
  elements.uploadMessage.classList.remove("error");
  if (!file || !file.name.toLowerCase().endsWith(".xlsx")) {
    elements.uploadMessage.classList.add("error");
    elements.uploadMessage.textContent = "请选择.xlsx文件。";
    return;
  }
  const button = elements.uploadForm.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "正在检查五张表……";
  try {
    const reason = elements.uploadForm.elements.replacementReason.value.trim();
    const headers = { "X-File-Name": encodeURIComponent(file.name) };
    if (reason) headers["X-Replacement-Reason"] = encodeURIComponent(reason);
    const result = await request(`/api/tasks/${encodeURIComponent(selectedTaskId)}/files`, {
      method: "POST",
      headers,
      body: file,
    });
    if (result.file.dataImportStatus === "failed") {
      elements.uploadMessage.textContent = "文件已留存，数据存在阻断，请按右侧提示处理。";
    } else if (result.file.dataImport) {
      const pendingValueCount = result.file.dataImport.mappingSummary?.pendingValueCount || 0;
      elements.uploadMessage.textContent = pendingValueCount
        ? `导入完成，已保存${result.file.dataImport.totalRecordCount.toLocaleString("zh-CN")}行数据；发现${pendingValueCount}个平台新值，已放入基础资料待映射。`
        : `导入完成，已保存${result.file.dataImport.totalRecordCount.toLocaleString("zh-CN")}行数据。`;
    } else {
      elements.uploadMessage.textContent = "文件已留存，请按右侧提示处理。";
    }
    elements.uploadForm.reset();
    await loadTasks(true);
  } catch (error) {
    elements.uploadMessage.classList.add("error");
    elements.uploadMessage.textContent = error.message;
    if (error.payload && error.payload.existingFile) {
      await loadTaskDetail(selectedTaskId, null);
    }
  } finally {
    button.disabled = false;
    button.textContent = "导入并检查";
  }
}

async function submitPlatformBalanceWorkbook(event) {
  event.preventDefault();
  if (!selectedTaskId) return;
  const form = elements.platformBalanceForm;
  const file = form.elements.workbook.files[0];
  elements.platformBalanceMessage.textContent = "";
  elements.platformBalanceMessage.classList.remove("error");
  if (!file || !file.name.toLowerCase().endsWith(".xlsx")) {
    elements.platformBalanceMessage.classList.add("error");
    elements.platformBalanceMessage.textContent = "请选择包含逐笔资金、日汇总和月汇总的.xlsx文件。";
    return;
  }
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "正在反向核对……";
  try {
    const reason = form.elements.replacementReason.value.trim();
    const headers = { "X-File-Name": encodeURIComponent(file.name) };
    if (reason) headers["X-Replacement-Reason"] = encodeURIComponent(reason);
    const result = await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/platform-balance-files`,
      { method: "POST", headers, body: file }
    );
    const run = result.platformBalance.run;
    elements.platformBalanceMessage.textContent = run
      ? `完整性试运行完成：${run.matchedCount}项一致，${run.attentionCount}项待核。`
      : "文件已留存，但结构不符合当前模拟映射。";
    form.reset();
    await loadTaskDetail(selectedTaskId, null);
  } catch (error) {
    elements.platformBalanceMessage.classList.add("error");
    elements.platformBalanceMessage.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "导入并核对完整性";
  }
}

async function submitPendingSettlementWorkbook(event) {
  event.preventDefault();
  if (!selectedTaskId) return;
  const form = elements.pendingSettlementForm;
  const file = form.elements.workbook.files[0];
  elements.pendingSettlementMessage.textContent = "";
  elements.pendingSettlementMessage.classList.remove("error");
  if (!file || !file.name.toLowerCase().endsWith(".xlsx")) {
    elements.pendingSettlementMessage.classList.add("error");
    elements.pendingSettlementMessage.textContent = "请选择包含待结算订单和订单售后辅助的.xlsx文件。";
    return;
  }
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "正在分类……";
  try {
    const reason = form.elements.replacementReason.value.trim();
    const headers = { "X-File-Name": encodeURIComponent(file.name) };
    if (reason) headers["X-Replacement-Reason"] = encodeURIComponent(reason);
    const result = await request(
      `/api/tasks/${encodeURIComponent(selectedTaskId)}/pending-settlement-files`,
      { method: "POST", headers, body: file }
    );
    const run = result.pendingSettlement.run;
    elements.pendingSettlementMessage.textContent = run
      ? `分类完成：${run.totalResultCount}笔结果，${run.waitingCount}笔正常等待，${run.attentionCount}笔需跟踪，${run.excludedCount}笔已排除。`
      : "文件已留存，但结构不符合当前模拟映射。";
    form.reset();
    await loadTaskDetail(selectedTaskId, null);
  } catch (error) {
    elements.pendingSettlementMessage.classList.add("error");
    elements.pendingSettlementMessage.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "导入并分类";
  }
}

elements.primaryTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});
elements.configurationTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchConfigurationPanel(tab.dataset.configPanel));
});
elements.retryConfigurationButton.addEventListener("click", loadConfiguration);
elements.retryOperatingReportButton.addEventListener("click", loadOperatingReport);
elements.switchTaskButton.addEventListener("click", () => switchView("tasks"));
elements.goToReconcileButton.addEventListener("click", () => switchView("reconcile"));
elements.emptyGoToImportButton.addEventListener("click", () => switchView("import"));
elements.newTaskToggle.addEventListener("click", () => {
  setTaskDropdown(elements.newTaskDropdown.hidden);
});
elements.closeTaskDropdown.addEventListener("click", () => setTaskDropdown(false));
elements.form.elements.entityId.addEventListener("change", renderTaskStoreOptions);
elements.manageMasterDataButton.addEventListener("click", () => {
  setTaskDropdown(false);
  switchView("config");
  switchConfigurationPanel("base-data");
});
elements.form.addEventListener("submit", submitTask);
elements.refreshButton.addEventListener("click", () => loadTasks(true));
elements.retryButton.addEventListener("click", () => loadTasks(true));
elements.loadSampleButton.addEventListener("click", loadSample);
elements.uploadForm.addEventListener("submit", submitWorkbook);
elements.platformBalanceForm.addEventListener("submit", submitPlatformBalanceWorkbook);
elements.pendingSettlementForm.addEventListener("submit", submitPendingSettlementWorkbook);
elements.taskLifecycleButton.addEventListener("click", openTaskLifecycleDialog);
document.addEventListener("click", (event) => {
  if (elements.newTaskDropdown.hidden) return;
  if (!event.target.closest(".task-create-anchor")) setTaskDropdown(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setTaskDropdown(false);
    closeLifecycleDialog();
  }
});

setInitialMonth();
loadHealthAndRule();
loadMasterDataOptions();
loadTasks(false);
