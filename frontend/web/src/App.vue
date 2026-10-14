<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ApiClient, ApiError, StaleResponseError } from './api'
import { navigation } from './navigation'
import { folderLabels, type Category, type Draft, type Folder, type FolderCount, type MessageDetail, type MessageSummary, type RecipientDelivery, type SendStatus, type User } from './model'

const api = new ApiClient()
const user = ref<User | null>(null)
const login = reactive({ address: '', password: '' })
const loginBusy = ref(false)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const counts = ref<FolderCount[]>([])
const categories = ref<Category[]>([])
const messages = ref<MessageSummary[]>([])
const drafts = ref<Draft[]>([])
const selected = ref<MessageDetail | null>(null)
const editing = ref<Draft | null>(null)
const sending = ref<SendStatus | null>(null)
const activeFolder = ref<Folder>('INBOX')
const activeCategory = ref<string | null>(null)
const activeDrafts = ref(false)
const query = ref('')
const leftCollapsed = ref(false)
const listCollapsed = ref(false)
const mobileStep = ref<'folders' | 'list' | 'reader'>('folders')
const isMobile = ref(window.matchMedia('(max-width: 700px)').matches)
let listSequence = 0
let viewSequence = 0
let statusTimer: number | undefined

const pageTitle = computed(() => activeDrafts.value ? '草稿箱' : activeCategory.value ? categories.value.find(c => c.id === activeCategory.value)?.name ?? '我的分类' : folderLabels[activeFolder.value])
const countByFolder = computed(() => new Map(counts.value.map(item => [item.folder, item])))
const activeItems = computed(() => activeDrafts.value ? drafts.value : messages.value)
const workspaceClass = computed(() => [`mobile-step-${mobileStep.value}`, { 'left-collapsed': leftCollapsed.value, 'list-collapsed': listCollapsed.value }])

function explain(failure: unknown): string {
  if (failure instanceof StaleResponseError) return ''
  if (!(failure instanceof ApiError)) return '操作未完成，请稍后重试。'
  const labels: Record<string, string> = {
    AUTHENTICATION_FAILED: '账号或密码不正确。', RATE_LIMITED: '登录尝试过多，请稍后再试。',
    AUTHENTICATION_REQUIRED: '会话已失效，请重新登录。', RESOURCE_NOT_FOUND: '内容不存在或你无权访问。',
    VERSION_CONFLICT: '服务器已有更新，请重新载入后再编辑。', SERVICE_UNAVAILABLE: '服务暂不可写，已保留原有内容。',
    COMMIT_OUTCOME_UNKNOWN: '保存结果暂时无法确认，请先刷新核对，避免重复操作。', ATTACHMENT_TOTAL_EXCEEDED: '附件总量超过 4 MiB 或 20 个。',
	IDEMPOTENCY_CONFLICT: '同一请求键对应了不同内容，已拒绝覆盖原发送意图。', SEND_ALREADY_STARTED: '邮件已进入 SMTP 发送流程，无法取消。',
	UNKNOWN_RETRY_NOT_AUTHORIZED: '未找到可重试的 UNKNOWN，或重复风险确认无效。', DUPLICATE_RISK_CONFIRMATION_REQUIRED: '必须明确确认可能重复后才能重试。',
  }
  return labels[failure.code] ?? `操作未完成（${failure.code}）。`
}
function fail(failure: unknown): void { const message = explain(failure); if (message) error.value = message }
function clearFeedback(): void { error.value = ''; notice.value = '' }

async function signIn(): Promise<void> {
  clearFeedback(); loginBusy.value = true
  try { user.value = await api.login(login.address, login.password); login.password = ''; await enterMailbox() }
  catch (failure) { fail(failure) } finally { loginBusy.value = false }
}
async function signOut(): Promise<void> {
  clearFeedback(); try { await api.logout() } catch (failure) { fail(failure) }
  stopStatusPolling(); user.value = null; selected.value = null; editing.value = null; sending.value = null; messages.value = []; drafts.value = []; mobileStep.value = 'folders'
}
async function enterMailbox(): Promise<void> {
  await refreshSidebar()
  if (isMobile.value) { history.replaceState({ step: 'folders' }, '', location.href); await openFolder('INBOX', true) }
  else await openFolder('INBOX', false)
}
async function refreshSidebar(): Promise<void> {
  const [nextCounts, nextCategories] = await Promise.all([api.folders(), api.categories()]); counts.value = nextCounts; categories.value = nextCategories
}
async function openFolder(folder: Folder, push = true): Promise<void> {
  clearFeedback(); viewSequence += 1; activeFolder.value = folder; activeCategory.value = null; activeDrafts.value = false; selected.value = null; editing.value = null; mobileStep.value = 'list'; await loadList(push)
}
async function openDrafts(push = true): Promise<void> {
  clearFeedback(); viewSequence += 1; activeDrafts.value = true; activeCategory.value = null; selected.value = null; editing.value = null; mobileStep.value = 'list'
  const sequence = ++listSequence; loading.value = true
  try { const page = await api.drafts(); if (sequence === listSequence) drafts.value = page.items; if (push) pushHistory('list') } catch (failure) { fail(failure) } finally { if (sequence === listSequence) loading.value = false }
}
async function openCategory(category: Category): Promise<void> {
  clearFeedback(); viewSequence += 1; activeCategory.value = category.id; activeDrafts.value = false; selected.value = null; editing.value = null; mobileStep.value = 'list'; await loadList(true)
}
async function loadList(push = false): Promise<void> {
  const sequence = ++listSequence; loading.value = true
  try { const page = await api.messages(activeCategory.value ? null : activeFolder.value, activeCategory.value, query.value); if (sequence === listSequence) messages.value = page.items; if (push) pushHistory('list') }
  catch (failure) { fail(failure) } finally { if (sequence === listSequence) loading.value = false }
}
async function search(): Promise<void> { if (!activeDrafts.value) await loadList(false) }

async function openMessage(item: MessageSummary, push = true): Promise<void> {
	clearFeedback(); stopStatusPolling(); sending.value = null; const sequence = ++viewSequence; editing.value = null; loading.value = true
  try {
    let detail = await api.message(item.entryId)
    if (!detail.summary.read) detail = await api.changeMessage(item.entryId, { version: detail.summary.version, read: true })
    if (sequence !== viewSequence) return
    selected.value = detail; mobileStep.value = 'reader'; replaceSummary(detail.summary); await refreshSidebar(); if (push) pushHistory('reader')
  } catch (failure) { fail(failure) } finally { loading.value = false }
}
async function openDraft(item: Draft, push = true): Promise<void> {
	clearFeedback(); stopStatusPolling(); sending.value = null; const sequence = ++viewSequence; selected.value = null; loading.value = true
  try { const value = await api.draft(item.id); if (sequence !== viewSequence) return; editing.value = value; mobileStep.value = 'reader'; if (push) pushHistory('reader') } catch (failure) { fail(failure) } finally { loading.value = false }
}
async function compose(): Promise<void> {
	clearFeedback(); stopStatusPolling(); sending.value = null; const sequence = ++viewSequence; loading.value = true
  try { const value = await api.createDraft({ subject: '', textBody: '', htmlBody: '', to: [], cc: [], bcc: [], mode: 'COMPOSE' }); if (sequence !== viewSequence) return; editing.value = value; selected.value = null; activeDrafts.value = true; mobileStep.value = 'reader'; pushHistory('reader') }
  catch (failure) { fail(failure) } finally { loading.value = false }
}
async function saveDraft(): Promise<void> {
  if (!editing.value) return; clearFeedback(); loading.value = true
  try { const updated = await api.saveDraft(editing.value); drafts.value = (await api.drafts()).items; editing.value = updated; notice.value = '草稿已持久保存。'; mobileStep.value = 'reader' }
  catch (failure) { fail(failure) } finally { loading.value = false }
}
async function sendDraft(): Promise<void> {
  if (!editing.value) return
  clearFeedback(); loading.value = true
  try {
    const saved = await api.saveDraft(editing.value)
    const storageKey = `guihong_send_${saved.id}_${saved.version}`
    const key = sessionStorage.getItem(storageKey) ?? crypto.randomUUID()
    sessionStorage.setItem(storageKey, key)
    const intent = await api.sendDraft(saved, key)
    sending.value = { intent }
    editing.value = null
    drafts.value = (await api.drafts()).items
    notice.value = '已在本地耐久提交，正在查询逐收件人投递结果。'
    startStatusPolling(intent.id)
  } catch (failure) { fail(failure) } finally { loading.value = false }
}
async function refreshSendStatus(): Promise<void> {
  if (!sending.value) return
  try {
    sending.value = await api.sendStatus(sending.value.intent.id)
    const active = sending.value.delivery?.recipients.some(item => ['QUEUED', 'STARTED', 'RETRY_WAIT'].includes(item.state))
    if (!active && sending.value.delivery) stopStatusPolling()
  } catch (failure) { fail(failure); stopStatusPolling() }
}
function startStatusPolling(intent: string): void {
  stopStatusPolling()
  void api.sendStatus(intent).then(value => { sending.value = value }).catch(fail)
  statusTimer = window.setInterval(() => { void refreshSendStatus() }, 1000)
}
function stopStatusPolling(): void { if (statusTimer !== undefined) { window.clearInterval(statusTimer); statusTimer = undefined } }
async function cancelSend(): Promise<void> {
  if (!sending.value) return
  clearFeedback(); loading.value = true
  try { sending.value.delivery = await api.cancelSend(sending.value.intent.id); notice.value = '取消裁决已持久保存。'; stopStatusPolling() }
  catch (failure) { fail(failure); await refreshSendStatus() } finally { loading.value = false }
}
async function retryUnknown(item: RecipientDelivery): Promise<void> {
  if (!sending.value || !window.confirm(`下一跳可能已经接受发往 ${item.recipient} 的邮件。确认承担重复投递风险并重试？`)) return
  const prior = item.attempts.at(-1)?.id ?? 'unknown'
  const storageKey = `guihong_retry_${sending.value.intent.id}_${item.recipient}_${prior}`
  const key = sessionStorage.getItem(storageKey) ?? crypto.randomUUID()
  sessionStorage.setItem(storageKey, key)
  clearFeedback(); loading.value = true
  try { sending.value.delivery = await api.retryUnknown(sending.value.intent.id, item.recipient, key); notice.value = '已记录重复风险确认并创建一次重试资格。'; startStatusPolling(sending.value.intent.id) }
  catch (failure) { fail(failure) } finally { loading.value = false }
}
async function derive(mode: 'REPLY' | 'REPLY_ALL' | 'FORWARD'): Promise<void> {
  if (!selected.value) return; clearFeedback(); const sourceId = selected.value.summary.entryId; const sequence = ++viewSequence; loading.value = true
  try { const value = await api.deriveDraft(sourceId, mode); if (sequence !== viewSequence) return; editing.value = value; selected.value = null; activeDrafts.value = true; mobileStep.value = 'reader'; pushHistory('reader') }
  catch (failure) { fail(failure) } finally { loading.value = false }
}
async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file || !editing.value) return
  clearFeedback(); loading.value = true
  try { editing.value = await api.attach(editing.value, file); notice.value = '附件已保存。' } catch (failure) { fail(failure) } finally { input.value = ''; loading.value = false }
}
async function changeFolder(folder: Folder): Promise<void> {
  if (!selected.value) return; clearFeedback()
  try { const detail = await api.changeMessage(selected.value.summary.entryId, { version: selected.value.summary.version, folder }); selected.value = detail; replaceSummary(detail.summary); await refreshSidebar(); notice.value = `已移至${folderLabels[folder]}。` }
  catch (failure) { fail(failure) }
}
async function changeRead(read: boolean): Promise<void> {
  if (!selected.value) return; clearFeedback()
  try { const detail = await api.changeMessage(selected.value.summary.entryId, { version: selected.value.summary.version, read }); selected.value = detail; replaceSummary(detail.summary); await refreshSidebar(); notice.value = read ? '已标为已读。' : '已标为未读。' }
  catch (failure) { fail(failure) }
}
async function assignCategory(event: Event): Promise<void> {
  if (!selected.value) return; const value = (event.target as HTMLSelectElement).value; clearFeedback()
  try { const body = value ? { version: selected.value.summary.version, categoryId: value } : { version: selected.value.summary.version, clearCategory: true }; selected.value = await api.changeMessage(selected.value.summary.entryId, body); replaceSummary(selected.value.summary); await refreshSidebar() }
  catch (failure) { fail(failure) }
}
async function addCategory(): Promise<void> {
  const name = window.prompt('分类名称（最多 40 字）')?.trim(); if (!name) return
  try { await api.createCategory(name); await refreshSidebar() } catch (failure) { fail(failure) }
}
async function removeCategory(category: Category): Promise<void> {
  if (!window.confirm(`删除分类“${category.name}”？邮件不会被删除或移动。`)) return
  try { await api.deleteCategory(category); if (activeCategory.value === category.id) await openFolder('INBOX'); await refreshSidebar() } catch (failure) { fail(failure) }
}
function replaceSummary(value: MessageSummary): void { const index = messages.value.findIndex(item => item.entryId === value.entryId); if (index >= 0) messages.value.splice(index, 1, value) }
function activate(item: (typeof navigation)[number]): void { if (item.id === 'compose') void compose(); else if (item.id === 'drafts') void openDrafts(); else if (item.folder) void openFolder(item.folder) }
function editAddresses(kind: 'to' | 'cc' | 'bcc', event: Event): void { if (editing.value) editing.value[kind] = (event.target as HTMLInputElement).value.split(',').map(value => value.trim()).filter(Boolean) }
function backMobile(): void { if (mobileStep.value === 'reader') mobileStep.value = 'list'; else if (mobileStep.value === 'list') mobileStep.value = 'folders' }
function pushHistory(step: 'list' | 'reader'): void { if (isMobile.value) history.pushState({ step }, '', location.href) }
function onPop(event: PopStateEvent): void { if (isMobile.value) mobileStep.value = event.state?.step === 'reader' ? 'reader' : event.state?.step === 'list' ? 'list' : 'folders' }
function onResize(): void { isMobile.value = window.matchMedia('(max-width: 700px)').matches }

onMounted(async () => {
  window.addEventListener('popstate', onPop); window.addEventListener('resize', onResize)
  try { user.value = await api.me(); await enterMailbox() } catch (failure) { if (!(failure instanceof ApiError && failure.status === 401)) fail(failure) }
})
onBeforeUnmount(() => { stopStatusPolling(); window.removeEventListener('popstate', onPop); window.removeEventListener('resize', onResize) })
</script>

<template>
  <main v-if="!user" class="login-shell">
    <section class="login-panel" aria-labelledby="brand-title">
      <p class="seal" aria-hidden="true">鸿</p>
      <h1 id="brand-title">归鸿</h1><p class="brand-line">云水之间，归鸿有信。</p>
      <form @submit.prevent="signIn" class="login-form">
        <label>邮箱地址<input v-model="login.address" type="email" autocomplete="username" required /></label>
        <label>密码<input v-model="login.password" type="password" autocomplete="current-password" required /></label>
        <button class="primary" :disabled="loginBusy">{{ loginBusy ? '正在验证…' : '进入邮箱' }}</button>
      </form>
      <p v-if="error" class="alert" role="alert">{{ error }}</p>
    </section>
  </main>

  <main v-else class="app-shell">
    <header class="topbar">
      <button class="mobile-back" type="button" @click="backMobile" aria-label="返回上一层">‹</button>
      <div class="brand"><span class="brand-mark">鸿</span><strong>归鸿</strong></div>
      <form class="search" role="search" @submit.prevent="search"><label class="sr-only" for="mail-search">搜索邮件</label><input id="mail-search" v-model="query" :disabled="activeDrafts" placeholder="搜索发件人、主题与正文" /><button :disabled="activeDrafts">搜索</button></form>
      <div class="account"><span>{{ user.display_name }}</span><button type="button" @click="signOut">退出</button></div>
    </header>
    <p v-if="error" class="global-message alert" role="alert">{{ error }}</p><p v-else-if="notice" class="global-message notice" role="status">{{ notice }}</p>

    <section class="workspace" :class="workspaceClass">
      <aside class="pane nav-pane" aria-label="邮箱目录">
        <button class="collapse collapse-left" type="button" @click="leftCollapsed = !leftCollapsed" :aria-expanded="!leftCollapsed" aria-label="折叠或展开目录栏">{{ leftCollapsed ? '›' : '‹' }}</button>
        <nav>
          <button v-for="item in navigation" :key="item.id" type="button" class="nav-item" :class="{ active: item.folder ? !activeDrafts && !activeCategory && activeFolder === item.folder : item.id === 'drafts' && activeDrafts }" @click="activate(item)">
            <span class="nav-glyph" aria-hidden="true">{{ item.glyph }}</span><span class="nav-label">{{ item.label }}</span>
            <span v-if="item.folder && countByFolder.get(item.folder)?.unread" class="badge" :aria-label="`${countByFolder.get(item.folder)?.unread} 封未读`">{{ countByFolder.get(item.folder)?.unread }}</span>
          </button>
          <div class="category-title"><span class="nav-label">我的分类</span><button type="button" @click="addCategory" aria-label="新建分类">＋</button></div>
          <div v-if="categories.length === 0" class="empty nav-label">尚未创建分类</div>
          <div v-for="category in categories" :key="category.id" class="category-row">
            <button type="button" class="nav-item" :class="{ active: activeCategory === category.id }" @click="openCategory(category)"><span class="nav-glyph">类</span><span class="nav-label">{{ category.name }}</span><span v-if="category.unread" class="badge">{{ category.unread }}</span></button>
            <button class="category-delete nav-label" type="button" @click="removeCategory(category)" :aria-label="`删除分类 ${category.name}`">×</button>
          </div>
        </nav>
      </aside>

      <section class="pane list-pane" :aria-label="pageTitle">
        <button class="collapse collapse-list" type="button" @click="listCollapsed = !listCollapsed" :aria-expanded="!listCollapsed" aria-label="折叠或展开邮件列表">{{ listCollapsed ? '›' : '‹' }}</button>
        <div class="list-heading"><div><p class="eyebrow">{{ activeDrafts ? 'DRAFTS' : 'MAILBOX' }}</p><h2>{{ pageTitle }}</h2></div><span>{{ activeItems.length }} 项</span></div>
        <div v-if="loading && activeItems.length === 0" class="empty">正在读取真实邮箱数据…</div>
        <div v-else-if="activeItems.length === 0" class="empty">这里暂时没有内容。</div>
        <button v-for="item in messages" v-show="!activeDrafts" :key="item.entryId" class="message-row" :class="{ unread: !item.read, selected: selected?.summary.entryId === item.entryId }" type="button" @click="openMessage(item)">
          <span class="row-top"><strong>{{ item.fromName || item.fromAddress }}</strong><time>{{ new Date(item.receivedAt).toLocaleDateString('zh-CN') }}</time></span><span class="subject">{{ item.subject || '（无主题）' }}</span><span class="preview">{{ item.preview }}</span><span v-if="item.attachmentCount" class="attachment-note">附件 {{ item.attachmentCount }}</span>
        </button>
        <button v-for="item in drafts" v-show="activeDrafts" :key="item.id" class="message-row" :class="{ selected: editing?.id === item.id }" type="button" @click="openDraft(item)">
          <span class="row-top"><strong>草稿</strong><time>{{ new Date(item.updatedAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}</time></span><span class="subject">{{ item.subject || '（无主题）' }}</span><span class="preview">{{ item.to.join(', ') || '尚未填写收件人' }}</span>
        </button>
      </section>

      <article class="pane reader-pane" aria-live="polite">
        <div v-if="!selected && !editing && !sending" class="reader-empty"><span aria-hidden="true">𓅱</span><h2>万里归鸿</h2><p>从左侧选择一封邮件，或开始写信。</p></div>
        <section v-if="selected" class="message-detail">
          <div class="reader-actions"><button type="button" @click="derive('REPLY')">回复</button><button type="button" @click="derive('REPLY_ALL')">全部回复</button><button type="button" @click="derive('FORWARD')">转发</button><button type="button" @click="changeRead(!selected.summary.read)">{{ selected.summary.read ? '标为未读' : '标为已读' }}</button><button type="button" @click="changeFolder('ARCHIVE')">归档</button><button type="button" @click="changeFolder('SPAM')">垃圾邮件</button><button type="button" @click="changeFolder('TRASH')">删除</button><button v-if="selected.summary.folder !== 'INBOX'" type="button" @click="changeFolder('INBOX')">恢复到收件箱</button></div>
          <header class="mail-header"><p class="eyebrow">{{ folderLabels[selected.summary.folder] }}</p><h1>{{ selected.summary.subject || '（无主题）' }}</h1><p><strong>{{ selected.summary.fromName || selected.summary.fromAddress }}</strong> &lt;{{ selected.summary.fromAddress }}&gt;</p><p class="recipients">收件人：{{ selected.recipients.filter(r => r.kind === 'TO').map(r => r.address).join(', ') || '未提供' }}</p><time>{{ new Date(selected.summary.sentAt || selected.summary.receivedAt).toLocaleString('zh-CN') }}</time>
            <label class="category-select">分类<select :value="selected.summary.categoryId || ''" @change="assignCategory"><option value="">未分类</option><option v-for="category in categories" :key="category.id" :value="category.id">{{ category.name }}</option></select></label>
          </header>
          <iframe v-if="selected.safeHtml" class="safe-mail" sandbox="" title="经过安全清理的邮件正文" :srcdoc="selected.safeHtml"></iframe><pre v-else class="plain-mail">{{ selected.textBody }}</pre>
          <section v-if="selected.attachments.length" class="attachments" aria-label="附件"><h2>附件</h2><a v-for="attachment in selected.attachments" :key="attachment.id" :href="`/api/mailbox/messages/${selected.summary.entryId}/attachments/${attachment.id}`">{{ attachment.fileName }} · {{ Math.ceil(attachment.size / 1024) }} KiB</a></section>
        </section>

        <form v-if="editing" class="draft-editor" @submit.prevent="saveDraft">
          <div class="reader-actions"><button class="primary" type="submit" :disabled="loading">保存草稿</button><button type="button" :disabled="loading" @click="sendDraft">发送</button><label class="upload">添加附件<input type="file" @change="upload" /></label></div>
          <p class="draft-truth">“已提交”仅表示本地内容与发送意图已耐久保存；逐收件人结果以下方投递回执为准。</p>
          <label>收件人<input :value="editing.to.join(', ')" @input="editAddresses('to', $event)" placeholder="alice@guihong.test, bob@guihong.test" /></label>
          <details><summary>抄送与密送</summary><label>抄送<input :value="editing.cc.join(', ')" @input="editAddresses('cc', $event)" /></label><label>密送<input :value="editing.bcc.join(', ')" @input="editAddresses('bcc', $event)" /></label></details>
          <label>主题<input v-model="editing.subject" maxlength="998" /></label><label class="body-label">正文<textarea v-model="editing.textBody"></textarea></label>
          <section v-if="editing.attachments.length" class="attachments"><h2>已保存附件</h2><a v-for="attachment in editing.attachments" :key="attachment.id" :href="`/api/mailbox/drafts/${editing.id}/attachments/${attachment.id}`">{{ attachment.fileName }} · {{ Math.ceil(attachment.size / 1024) }} KiB</a></section>
          <p class="draft-meta">草稿版本 {{ editing.version }} · {{ new Date(editing.updatedAt).toLocaleString('zh-CN') }}</p>
        </form>
        <section v-if="sending" class="send-receipt" aria-live="polite">
          <div class="reader-actions"><button type="button" @click="refreshSendStatus">刷新回执</button><button v-if="!sending.delivery?.everStarted && sending.delivery?.state !== 'CANCELLED'" type="button" :disabled="loading" @click="cancelSend">取消发送</button></div>
          <p class="eyebrow">SUBMITTED_LOCAL</p><h1>发送意图已耐久保存</h1>
          <p class="receipt-meta">Intent {{ sending.intent.id }} · raw {{ sending.intent.rawSha256.slice(0, 16) }}…</p>
          <p v-if="!sending.delivery" class="draft-truth">投递 Worker 尚未建立 scope；此状态不代表已投递。</p>
          <div v-else>
            <p class="scope-state">Scope：{{ sending.delivery.state }} · {{ sending.delivery.everStarted ? 'SMTP 尝试已经开始，不能撤回' : '尚未开始 SMTP 尝试' }}</p>
            <article v-for="item in sending.delivery.recipients" :key="item.id" class="recipient-result">
              <div><strong>{{ item.recipient }}</strong><span :class="`state state-${item.state.toLowerCase()}`">{{ item.state }}</span></div>
              <p>尝试 {{ item.attemptCount }} 次<span v-if="item.attempts.at(-1)?.smtpCode"> · SMTP {{ item.attempts.at(-1)?.smtpCode }}</span><span v-if="item.attempts.at(-1)"> · 阶段 {{ item.attempts.at(-1)?.lastStage }}</span></p>
              <p v-if="item.state === 'UNKNOWN'" class="unknown-copy">下一跳是否接受无法确认，自动重投已暂停。原尝试及证据已保留。</p>
              <button v-if="item.state === 'UNKNOWN'" type="button" :disabled="loading" @click="retryUnknown(item)">确认可能重复并重试</button>
            </article>
          </div>
        </section>
      </article>
    </section>
  </main>
</template>
