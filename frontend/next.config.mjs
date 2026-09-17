// frontend/next.config.mjs
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Docker (EC2 등) 배포용 — node server.js 단독 실행 가능한 standalone 출력
  output: 'standalone',

  // API 프록시 설정 (개발용 — `npm run dev` 일 때만 의미. production 에선 nginx 가 `/api` reverse proxy)
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ]
  }
}

export default nextConfig
