import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// 사용되는 글자의 서브셋만 동적으로 로드하는 Pretendard 가변 폰트
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import { App } from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
