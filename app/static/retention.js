import {request, element} from './client.js';

const form = document.querySelector('#disposal-form');
const disputeForm = document.querySelector('#dispute-form');
const runLine = document.querySelector('#disposal-run');
const daysInput = document.querySelector('#retention-days');
const resultBox = document.querySelector('#disposal-result');
const downloadLink = document.querySelector('#disposal-download');

const verdictLabels = {PURGED: '已清空敏感值', RETAINED: '原凭据完整保留'};
const reasonLabels = {
  BATCH_NOT_APPROVED: '批次未签发',
  DISPUTE_OPEN: '存在未结争议',
  RETENTION_NOT_DUE: '保留期未满',
};

function verdict(result) {
  const box = element('div');
  const head = element('p', `${verdictLabels[result.disposition] || result.disposition} · 第 ${result.basis.run_revision} 版批次`,
    {class: 'verdict', 'data-disposition': result.disposition});
  box.append(head);
  const policy = result.policy;
  box.append(element('p', `保留期 ${policy.retention_days} 天 · 截止 ${policy.retain_until} · 未结争议 ${policy.open_disputes}`));
  if (policy.reasons.length) {
    box.append(element('p', policy.reasons.map(code => reasonLabels[code] || code).join('；')));
  }
  const recon = result.reconciliation;
  box.append(element('p', `凭据 ${recon.voucher_rows} 行 · 分组 ${recon.cases.join('、') || '—'} · 金额账 ${Object.entries(recon.amounts_cents).map(([k, v]) => `${k}=${v}`).join('，') || '—'}`));
  if (result.redaction.purged_fields.length) {
    box.append(element('p', `已清空字段：${result.redaction.purged_fields.join('、')}（不可还原）`));
  }
  return box;
}

export function bindRetention(announce, perform) {
  form.addEventListener('submit', event => {
    event.preventDefault();
    const runId = form.dataset.run;
    perform(async () => {
      const params = new URLSearchParams();
      if (daysInput.value) params.set('retention_days', daysInput.value);
      const query = params.toString();
      const result = await request(`/api/runs/${runId}/disposal${query ? `?${query}` : ''}`,
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      showResult(runId, result);
      announce(result.disposition === 'PURGED' ? '处置完成：敏感值已清空' : '处置完成：原凭据保留');
    });
  });

  disputeForm.addEventListener('submit', event => {
    event.preventDefault();
    const runId = form.dataset.run;
    const note = disputeForm.querySelector('#dispute-note').value;
    perform(async () => {
      await request(`/api/runs/${runId}/disputes`,
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({note})});
      disputeForm.reset();
      announce('争议已登记，未结前原凭据将完整保留');
      await refreshResult(runId);
    });
  });
}

function showResult(runId, result) {
  resultBox.hidden = false;
  resultBox.replaceChildren(verdict(result));
  downloadLink.hidden = false;
  // 页面与下载共用同一处置结果端点
  downloadLink.href = `/api/runs/${runId}/disposal/download`;
}

async function refreshResult(runId) {
  try {
    const result = await request(`/api/runs/${runId}/disposal`);
    showResult(runId, result);
  } catch {
    /* 尚无处置结果时保持面板待操作状态 */
  }
}

export function activateRetention(batch) {
  form.hidden = disputeForm.hidden = !batch;
  resultBox.replaceChildren();
  resultBox.hidden = true;
  downloadLink.hidden = true;
  if (!batch) return;
  form.dataset.run = batch.id;
  runLine.textContent = `${batch.id.slice(0, 10)} · ${batch.status} · r${batch.revision}`;
  refreshResult(batch.id);
}
