import { lazy, Suspense } from 'react'
import {
  createBrowserRouter,
  RouterProvider,
  Navigate,
  Outlet,
} from 'react-router-dom'
import { RequireAuth } from './RequireAuth'
import { AppShell } from '@components/layout/AppShell'
import { Spinner } from '@components/ui'

// Lazy-load all pages so the initial bundle stays small
const LoginPage          = lazy(() => import('@/modules/auth/pages/LoginPage'))
const DashboardPage      = lazy(() => import('@/modules/dashboard/pages/DashboardPage'))
const InvoicePage        = lazy(() => import('@/modules/extraction/pages/InvoicePage'))
const BankStatementPage  = lazy(() => import('@/modules/extraction/pages/BankStatementPage'))
const OCRPage            = lazy(() => import('@/modules/ocr/pages/OCRPage'))
const ScraperPage        = lazy(() => import('@/modules/scraper/pages/ScraperPage'))
const ClassificationPage = lazy(() => import('@/modules/classification/pages/ClassificationPage'))
const ChatbotPage        = lazy(() => import('@/modules/chatbot/pages/ChatbotPage'))

function Loading() {
  return (
    <div className="flex h-full min-h-48 items-center justify-center">
      <Spinner />
    </div>
  )
}

function ProtectedLayout() {
  return (
    <RequireAuth>
      <AppShell>
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
      </AppShell>
    </RequireAuth>
  )
}

/**
 * FIX: Added `future` flags to silence React Router v6 → v7 migration warnings.
 *   v7_startTransition — wraps navigation state updates in React.startTransition
 *   v7_relativeSplatPath — fixes relative path resolution in splat routes
 * These are opt-in to v7 behaviour and have zero breaking impact on our routes.
 */
const router = createBrowserRouter(
  [
    {
      path: '/login',
      element: (
        <Suspense fallback={<Loading />}>
          <LoginPage />
        </Suspense>
      ),
    },
    {
      path: '/',
      element: <ProtectedLayout />,
      children: [
        { index: true,           element: <Navigate to="/dashboard" replace /> },
        { path: 'dashboard',     element: <DashboardPage /> },
        { path: 'invoice',       element: <InvoicePage /> },
        { path: 'bank-statement',element: <BankStatementPage /> },
        { path: 'ocr',           element: <OCRPage /> },
        { path: 'scraper',       element: <ScraperPage /> },
        { path: 'classification',element: <ClassificationPage /> },
        { path: 'chatbot',       element: <ChatbotPage /> },
      ],
    },
    { path: '*', element: <Navigate to="/dashboard" replace /> },
  ],
  {
    future: {
      v7_startTransition:    true,
      v7_relativeSplatPath:  true,
    },
  },
)

export function AppRouter() {
  return <RouterProvider router={router} />
}