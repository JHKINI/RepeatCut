import React from 'react'
import ReactDOM from 'react-dom/client'
import './vibe-design/index.css'
import './index.css'
// Apple 스타일 테마. 예전 디자인으로 되돌리려면 아래 한 줄을 지우거나 맨 앞에 // 를 붙이세요.
import './theme-apple.css'
// 보라색 그래픽 배경. 배경 이미지만 빼고 싶으면 아래 한 줄을 지우세요.
import './theme-hero.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><App /></React.StrictMode>,
)
