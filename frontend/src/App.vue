<template>
  <el-container style="min-height: 100vh;">
    <el-header style="padding: 20px 0; text-align: center;">
      <h1 style="margin: 0; font-size: 24px;">BackendTestForge</h1>
      <p style="margin: 4px 0 0; color: #909399; font-size: 14px;">
        多 Agent 后端质量检测系统
      </p>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
</script>

<style>
body {
  margin: 0;
  background: #f5f7fa;
}
</style>
