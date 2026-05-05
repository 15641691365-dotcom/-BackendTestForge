<template>
  <div style="max-width: 700px; margin: 0 auto;">
    <el-card>
      <template #header>
        <span>创建新测试任务</span>
      </template>

      <el-form :model="form" label-width="120px">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="例如: user-service-test" />
        </el-form-item>

        <el-form-item label="服务地址">
          <el-input v-model="form.startup_config" placeholder="http://localhost:8001" />
          <div style="color: #909399; font-size: 12px; margin-top: 4px;">
            被测后端服务的访问地址（确保服务已在运行）
          </div>
        </el-form-item>

        <el-form-item label="项目路径（可选）">
          <el-input
            v-model="form.project_path"
            placeholder="/home/user/my-project/backend"
          />
          <div style="color: #909399; font-size: 12px; margin-top: 4px;">
            代码扫描路径（用于自动识别 API 路由）。留空则只测服务地址不扫代码。
          </div>
        </el-form-item>

        <el-form-item label="测试目标（可选）">
          <el-input v-model="form.feature_name" placeholder="描述你想测试的功能，例如: 我想测用户的登录和注册流程" />
          <div style="color: #909399; font-size: 12px; margin-top: 4px;">
            留空则测试所有 API 路由。填写后系统自动识别相关接口进行测试。
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="submitTask" :loading="loading" size="large">
            开始分析
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        closable
        @close="error = ''"
      />

      <el-alert
        v-if="successMsg"
        :title="successMsg"
        type="success"
        show-icon
        closable
        @close="successMsg = ''"
      />
    </el-card>

    <!-- 最近任务 -->
    <el-card style="margin-top: 16px;">
      <template #header>
        <span>最近任务</span>
      </template>
      <el-table :data="recentTasks" style="width: 100%" v-loading="loadingTasks" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button type="primary" link @click="viewTask(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const API_BASE = 'http://localhost:8000'
const router = useRouter()

const form = ref({
  name: '',
  project_path: '',
  startup_mode: 'manual',
  startup_config: '',
  feature_name: '',
})

const loading = ref(false)
const error = ref('')
const successMsg = ref('')
const recentTasks = ref([])
const loadingTasks = ref(false)

async function submitTask() {
  if (!form.value.name) {
    error.value = '任务名称不能为空'
    return
  }
  if (!form.value.startup_config) {
    error.value = '服务地址不能为空'
    return
  }
  loading.value = true
  error.value = ''
  successMsg.value = ''
  try {
    const res = await axios.post(`${API_BASE}/api/tasks`, form.value)
    const task = res.data
    successMsg.value = `任务 #${task.id} 创建成功！正在跳转...`
    setTimeout(() => {
      router.push(`/task/${task.id}`)
    }, 800)
  } catch (e) {
    error.value = `创建失败: ${e.message}`
  } finally {
    loading.value = false
  }
}

async function loadRecentTasks() {
  loadingTasks.value = true
  try {
    const res = await axios.get(`${API_BASE}/api/tasks?limit=10`)
    recentTasks.value = res.data
  } catch (e) {
    // silently fail
  } finally {
    loadingTasks.value = false
  }
}

function viewTask(id) {
  router.push(`/task/${id}`)
}

function statusType(status) {
  const map = { pending: 'info', running: 'warning', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { pending: '待执行', running: '运行中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

onMounted(() => {
  loadRecentTasks()
})
</script>
