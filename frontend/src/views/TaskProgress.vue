<template>
  <div style="max-width: 900px; margin: 0 auto;">
    <el-button @click="$router.push('/')" style="margin-bottom: 16px;">
      ← 返回首页
    </el-button>

    <el-card v-loading="loading">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>任务 #{{ taskId }}: {{ task?.name }}</span>
          <el-tag :type="statusType(task?.status)" size="large">
            {{ task?.status }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="项目路径">{{ task?.project_path }}</el-descriptions-item>
        <el-descriptions-item label="启动方式">{{ task?.startup_mode }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ task?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ task?.updated_at }}</el-descriptions-item>
        <el-descriptions-item v-if="task?.feature_name" label="测试功能" :span="2">
          <el-tag type="success">{{ task?.feature_name }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item v-if="task?.error_message" label="错误信息" :span="2">
          <el-tag type="danger">{{ task?.error_message }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- Agent 执行记录 -->
    <el-card style="margin-top: 16px;" v-if="agentRuns.length > 0">
      <template #header>
        <span>Agent 执行记录</span>
      </template>

      <div v-for="run in agentRuns" :key="run.id" style="margin-bottom: 16px;">
        <el-timeline>
          <el-timeline-item
            :type="run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'warning'"
            :timestamp="run.started_at"
          >
            <h4 style="margin: 0 0 8px;">{{ agentLabel(run.agent_name) }}</h4>
            <el-tag :type="run.status === 'completed' ? 'success' : 'danger'" size="small">
              {{ statusLabel(run.status) }}
            </el-tag>
            <div v-if="run.result_json" style="margin-top: 8px; text-align: left;">
              <el-button @click="toggleResult(run.id)" size="small">
                {{ expandedResult === run.id ? '收起' : '查看' }} 结果
              </el-button>
              <pre v-if="expandedResult === run.id" class="result-json">{{ prettyJson(run.result_json) }}</pre>
            </div>
            <p v-if="run.error_message" style="color: #f56c6c;">{{ run.error_message }}</p>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-card>

    <!-- 代码解析结果 -->
    <el-card style="margin-top: 16px;" v-if="parseResult">
      <template #header>
        <span>代码解析结果</span>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="编程语言">{{ parseResult.tech_stack?.language }}</el-descriptions-item>
        <el-descriptions-item label="框架">{{ parseResult.tech_stack?.framework }}</el-descriptions-item>
        <el-descriptions-item label="入口文件">{{ parseResult.tech_stack?.entry_point }}</el-descriptions-item>
        <el-descriptions-item label="Web 服务">{{ parseResult.tech_stack?.web_server }}</el-descriptions-item>
        <el-descriptions-item label="可信度" :span="2">
          <el-tag :type="parseResult.tech_stack?.confidence === 'high' ? 'success' : 'warning'">
            {{ confidenceLabel(parseResult.tech_stack?.confidence) }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 路由列表 -->
      <h3 style="margin: 20px 0 10px;">
        API 路由 ({{ parseResult.routes_from_grep?.length || 0 }})
      </h3>
      <el-table :data="parseResult.routes_from_grep || []" stripe max-height="400" style="width: 100%;">
        <el-table-column prop="method" label="方法" width="80">
          <template #default="{ row }">
            <el-tag :type="methodColor(row.method)" size="small">{{ row.method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="path" label="路径" min-width="200" />
        <el-table-column prop="file" label="文件" min-width="300" />
      </el-table>

      <!-- 关键文件 -->
      <h3 style="margin: 20px 0 10px;">
        关键文件 ({{ parseResult.key_files?.length || 0 }})
      </h3>
      <el-table :data="parseResult.key_files || []" stripe style="width: 100%;">
        <el-table-column prop="path" label="文件路径" min-width="300" />
        <el-table-column prop="size" label="大小" width="80" />
        <el-table-column prop="priority" label="优先级" width="80" />
      </el-table>
    </el-card>

    <!-- 压测结果 -->
    <el-card style="margin-top: 16px;" v-if="loadTestData">
      <template #header>
        <span>压测结果</span>
      </template>

      <!-- 指标卡片 -->
      <el-row :gutter="16" style="margin-bottom: 20px;">
        <el-col :span="6">
          <el-card shadow="never" style="text-align: center;">
            <div style="font-size: 28px; font-weight: bold; color: #409eff;">{{ loadTestData.max_concurrency }}</div>
            <div style="color: #909399; font-size: 12px;">最大安全并发</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" style="text-align: center;">
            <div style="font-size: 28px; font-weight: bold; color: #67c23a;">{{ loadTestData.qps_avg }}</div>
            <div style="color: #909399; font-size: 12px;">平均 QPS</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" style="text-align: center;">
            <div style="font-size: 22px; font-weight: bold; color: #e6a23c;">{{ loadTestData.latency_p95 }}ms</div>
            <div style="color: #909399; font-size: 12px;">P95 延迟</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" style="text-align: center;">
            <div style="font-size: 22px; font-weight: bold; color: #f56c6c;">{{ loadTestData.latency_p99 }}ms</div>
            <div style="color: #909399; font-size: 12px;">P99 延迟</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 曲线图 -->
      <div v-if="loadTestData.curve_data && loadTestData.curve_data.length > 1" style="height: 300px;">
        <v-chart :option="chartOption" autoresize />
      </div>

      <!-- 瓶颈 -->
      <el-alert
        v-if="loadTestData.bottleneck"
        :title="loadTestData.bottleneck"
        type="warning"
        show-icon
        style="margin-top: 12px;"
      />
    </el-card>

    <!-- 修复文档 -->
    <el-card style="margin-top: 16px;" v-if="fixDocument">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>修复文档</span>
          <el-button type="primary" size="small" @click="downloadFixDoc">
            下载 .md
          </el-button>
        </div>
      </template>

      <div style="display: flex; gap: 16px; margin-bottom: 16px;" v-if="reportOverview">
        <el-card shadow="never" style="flex: 1; text-align: center;">
          <div style="font-size: 32px; font-weight: bold; color: gradeColor(reportOverview.overall_grade);">
            {{ reportOverview.overall_grade }}
          </div>
          <div style="color: #909399; font-size: 12px;">综合评分</div>
        </el-card>
        <el-card shadow="never" style="flex: 1; text-align: center;">
          <div style="font-size: 24px; font-weight: bold;">{{ reportOverview.routes_count }}</div>
          <div style="color: #909399; font-size: 12px;">API 路由数</div>
        </el-card>
        <el-card shadow="never" style="flex: 1; text-align: center;">
          <div style="font-size: 24px; font-weight: bold;">{{ reportOverview.language }}</div>
          <div style="color: #909399; font-size: 12px;">编程语言</div>
        </el-card>
      </div>

      <div class="markdown-content" v-html="renderedFixDoc"></div>
    </el-card>

    <div v-if="task?.status === 'pending' || task?.status === 'running'" style="text-align: center; margin-top: 24px;">
      <el-button type="primary" @click="triggerRun" :loading="triggering" size="large">
        {{ task?.status === 'running' ? '运行中...' : '开始执行' }}
      </el-button>
    </div>

    <div v-if="task?.status === 'pending'" style="text-align: center; margin-top: 12px; color: #909399;">
      点击"开始执行"启动分析流水线。
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useRoute } from 'vue-router'
import axios from 'axios'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const API_BASE = 'http://localhost:8000'
const route = useRoute()
const taskId = Number(route.params.id)

const task = ref(null)
const loading = ref(true)
const triggering = ref(false)
const agentRuns = ref([])
const parseResult = ref(null)
const expandedResult = ref(null)
const loadTestData = ref(null)
const fixDocument = ref(null)
const reportOverview = ref(null)
const renderedFixDoc = ref('')
const chartOption = ref({})
let pollTimer = null

async function loadTask() {
  try {
    const res = await axios.get(`${API_BASE}/api/tasks/${taskId}`)
    task.value = res.data
    agentRuns.value = res.data.agent_runs || []

    // Extract parse result from completed code_parser run
    const parserRun = agentRuns.value.find(r => r.agent_name === 'code_parser' && r.status === 'completed')
    if (parserRun && parserRun.result_json) {
      parseResult.value = JSON.parse(parserRun.result_json)
    }

    // Load load test results
    loadLoadTestResults()

    // Extract fix document from completed doc_builder run
    const docRun = agentRuns.value.find(r => r.agent_name === 'doc_builder' && r.status === 'completed')
    if (docRun && docRun.result_json) {
      try {
        const docData = JSON.parse(docRun.result_json)
        reportOverview.value = docData.overview
        // The full fix document needs to be loaded from the report endpoint
        loadFixDocument()
      } catch {}
    }

    loading.value = false
  } catch (e) {
    loading.value = false
  }
}

async function loadLoadTestResults() {
  try {
    const res = await axios.get(`${API_BASE}/api/tasks/${taskId}/load-results`)
    if (res.data.has_results) {
      loadTestData.value = res.data
      buildChart()
    }
  } catch {
    // Task might not exist yet, ignore
  }
}

function buildChart() {
  if (!loadTestData.value?.curve_data || loadTestData.value.curve_data.length < 2) return

  const data = loadTestData.value.curve_data
  const vus = data.map(d => d.vus || 0)
  const qps = data.map(d => d.qps || 0)
  const p99 = data.map(d => d.p99 || 0)
  const errorRates = data.map(d => (d.error_rate || 0) * 100)

  chartOption.value = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['QPS', 'P99 (ms)', 'Error Rate (%)'], top: 0 },
    grid: { left: 50, right: 50, bottom: 30, top: 40 },
    xAxis: { type: 'category', data: vus.map(v => `${v} VUs`), name: 'Concurrency' },
    yAxis: [
      { type: 'value', name: 'QPS' },
      { type: 'value', name: 'Latency (ms)' },
    ],
    series: [
      { name: 'QPS', type: 'line', data: qps, smooth: true, itemStyle: { color: '#409eff' } },
      { name: 'P99 (ms)', type: 'line', data: p99, smooth: true, yAxisIndex: 1, itemStyle: { color: '#e6a23c' } },
      { name: 'Error Rate (%)', type: 'bar', data: errorRates, yAxisIndex: 1, itemStyle: { color: '#f56c6c' } },
    ],
  }
}

function gradeColor(grade) {
  const map = { A: '#67c23a', B: '#409eff', C: '#e6a23c', D: '#f56c6c' }
  return map[grade] || '#909399'
}

async function loadFixDocument() {
  const docRun = agentRuns.value.find(r => r.agent_name === 'doc_builder' && r.status === 'completed')
  if (!docRun || !docRun.result_json) return
  try {
    const data = JSON.parse(docRun.result_json)
    if (data.fix_document_preview) {
      fixDocument.value = data.fix_document_preview
      renderedFixDoc.value = simpleMarkdown(data.fix_document_preview)
    }
  } catch {}
}

function simpleMarkdown(text) {
  if (!text) return ''
  let html = text
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
    // Markdown tables → HTML tables
    // Match header row + separator row + data rows
    .replace(/(^\|.+\|\n)(^\|.+\|\n)((?:\|.+\|\n?)*)/gm, (match, headerRow, _sepRow, dataBlock) => {
      const headers = headerRow.split('|').filter(c => c.trim()).map(c => c.trim())
      if (headers.length === 0) return match
      let table = '<table><thead><tr>'
      headers.forEach(h => { table += `<th>${h}</th>` })
      table += '</tr></thead><tbody>'
      dataBlock.trim().split('\n').forEach(row => {
        const cells = row.split('|').filter(c => c.trim()).map(c => c.trim())
        if (cells.length > 0) {
          table += '<tr>'
          cells.forEach(c => { table += `<td>${c}</td>` })
          table += '</tr>'
        }
      })
      table += '</tbody></table>'
      return table
    })
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
  return `<p>${html}</p>`
}

function downloadFixDoc() {
  if (!fixDocument.value) return
  const blob = new Blob([fixDocument.value], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `fix-doc-task-${taskId}.md`
  a.click()
  URL.revokeObjectURL(url)
}

async function triggerRun() {
  triggering.value = true
  try {
    await axios.post(`${API_BASE}/api/tasks/${taskId}/run`)
    // Start polling for updates
    startPolling()
  } catch (e) {
    console.error('Trigger failed:', e)
  } finally {
    triggering.value = false
  }
}

function startPolling() {
  pollTimer = setInterval(() => {
    loadTask()
    // Stop polling when task completes or fails
    if (task.value && ['completed', 'failed'].includes(task.value.status)) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 2000)
}

function toggleResult(id) {
  expandedResult.value = expandedResult.value === id ? null : id
}

function prettyJson(str) {
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch {
    return str
  }
}

function statusType(status) {
  const map = { pending: 'info', running: 'warning', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { pending: '待执行', running: '运行中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

function agentLabel(name) {
  const map = { code_parser: '代码解析器', load_tester: '压测引擎', doc_builder: '报告生成器', orchestrator: '编排器' }
  return map[name] || name
}

function confidenceLabel(level) {
  const map = { high: '高', medium: '中', low: '低', manual: '手动设置' }
  return map[level] || level
}

function methodColor(method) {
  const map = { GET: '', POST: 'success', PUT: 'warning', DELETE: 'danger', PATCH: 'info' }
  return map[method] || ''
}

onMounted(() => {
  loadTask()
  // If already running, start polling
  if (task.value && task.value.status === 'running') {
    startPolling()
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.result-json {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 6px;
  overflow: auto;
  max-height: 400px;
  font-size: 12px;
  line-height: 1.5;
  text-align: left;
}

.markdown-content {
  background: #fff;
  padding: 16px;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
  font-size: 14px;
  line-height: 1.8;
  overflow-x: auto;
}

.markdown-content h1 { font-size: 22px; margin: 16px 0 8px; }
.markdown-content h2 { font-size: 18px; margin: 14px 0 6px; border-bottom: 1px solid #eee; padding-bottom: 4px; }
.markdown-content h3 { font-size: 16px; margin: 12px 0 4px; color: #303133; }
.markdown-content p { margin: 8px 0; }
.markdown-content pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
}
.markdown-content code {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
}
.markdown-content pre code {
  background: transparent;
  padding: 0;
}
.markdown-content ul { margin: 8px 0; padding-left: 20px; }
.markdown-content li { margin: 4px 0; }
.markdown-content table {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}
.markdown-content td, .markdown-content th {
  border: 1px solid #e4e7ed;
  padding: 8px 12px;
  text-align: left;
}
.markdown-content th {
  background: #f5f7fa;
  font-weight: 600;
}
</style>