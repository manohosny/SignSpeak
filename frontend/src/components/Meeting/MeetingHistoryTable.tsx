import { useQuery } from "@tanstack/react-query"
import type { MeetingPublic } from "@/client"
import { MeetingsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { QUERY_KEYS } from "@/lib/constants"

function statusVariant(status: string) {
  switch (status) {
    case "active":
      return "default" as const
    case "waiting":
      return "secondary" as const
    default:
      return "outline" as const
  }
}

function formatDate(dateStr?: string | null) {
  if (!dateStr) return "—"
  return new Date(dateStr).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function MeetingHistoryTable() {
  const { data, isLoading } = useQuery({
    queryKey: [QUERY_KEYS.MEETINGS],
    queryFn: () => MeetingsService.getMyMeetings({ limit: 20 }),
  })

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  const meetings = data?.data ?? []

  if (meetings.length === 0) {
    return (
      <div className="rounded-lg border p-8 text-center text-muted-foreground">
        No meetings yet. Create one to get started!
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Code</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Participants</TableHead>
          <TableHead>Date</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {meetings.map((meeting: MeetingPublic) => (
          <TableRow key={meeting.id}>
            <TableCell>
              <code className="font-mono font-medium">{meeting.code}</code>
            </TableCell>
            <TableCell>
              <Badge variant={statusVariant(meeting.status)}>
                {meeting.status}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {meeting.participants?.length ?? 0}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatDate(meeting.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
