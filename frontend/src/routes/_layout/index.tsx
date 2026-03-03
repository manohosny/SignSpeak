import { createFileRoute } from "@tanstack/react-router"

import { CreateMeetingDialog } from "@/components/Meeting/CreateMeetingDialog"
import { JoinMeetingDialog } from "@/components/Meeting/JoinMeetingDialog"
import { MeetingHistoryTable } from "@/components/Meeting/MeetingHistoryTable"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Dashboard - SignSpeak",
      },
    ],
  }),
})

function Dashboard() {
  const { user: currentUser } = useAuth()

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight truncate max-w-sm">
            Hi, {currentUser?.full_name || currentUser?.email} 👋
          </h1>
          <p className="text-muted-foreground">
            Start or join a meeting to communicate in real time.
          </p>
        </div>
        <div className="flex gap-2">
          <CreateMeetingDialog />
          <JoinMeetingDialog />
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4">Recent Meetings</h2>
        <MeetingHistoryTable />
      </div>
    </div>
  )
}
