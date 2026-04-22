import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const client = axios.create({ 
  baseURL: '/api',
  withCredentials: true // 🌟 新增：允许跨域携带和设置 Cookie
})

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default client