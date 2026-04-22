import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={{
      token: {
        colorPrimary: '#E2001A',       // BSH 品牌红
        colorLink: '#E2001A',
        borderRadius: 8,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif",
      },
      components: {
        Menu: {
          itemSelectedBg: '#fff1f2',
          itemSelectedColor: '#E2001A',
        },
        Layout: { siderBg: '#fff', headerBg: '#fff' },
      },
    }}>
      <App />
    </ConfigProvider>
  </StrictMode>,
)
