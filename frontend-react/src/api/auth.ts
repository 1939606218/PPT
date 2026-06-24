import client from './client'
import type { TokenOut } from '../types'
// 引入刚刚定义的 DeviceTokenOut（如果写在同一个文件里就一起引）
import type { DeviceTokenOut } from '../types' 

export const authApi = {
  login: (username: string, password: string) => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    return client.post<TokenOut>('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },

  register: (username: string, password: string) =>
    client.post<TokenOut>('/auth/register', { username, password }),

  me: () => client.get('/auth/me'),

  /** 
   * 内网 IP + 设备号 免密自动登录
   * 结合 localStorage 解决动态 IP 变化的问题
   */
  ipLogin: async () => {
    // 1. 从浏览器缓存读取设备号（第一次登录时为 null）
    const savedDeviceId = localStorage.getItem('intranet_device_id')

    // 2. 改为 POST 请求，并把 device_id 发给后端
    const response = await client.post<DeviceTokenOut>('/auth/ip-login', {
      device_id: savedDeviceId || null
    })

    // 3. 解决 TS 报错：安全地提取数据，并断言为 DeviceTokenOut 类型
    // 如果 response 包含 data 属性 (Axios包裹)，就取 response.data；否则认为它本身就是数据
    const payload = ('data' in response ? response.data : response) as DeviceTokenOut

    // 4. 将后端返回的 device_id 持久化保存
    if (payload && payload.device_id) {
      localStorage.setItem('intranet_device_id', payload.device_id)
    }

    return response
  },
}