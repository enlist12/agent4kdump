import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { getSession, listSessions } from "./api/client";
import { mockSession } from "./api/mock";
import { AppLayout } from "./components/AppLayout";
import { Dashboard } from "./pages/Dashboard";
import { SettingsView } from "./pages/SettingsView";
import { SessionDetailView } from "./pages/SessionDetailView";
import { useSessionStore } from "./stores/sessionStore";

export function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const queryClient = useQueryClient();
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const setActiveSessionId = useSessionStore((state) => state.setActiveSessionId);

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: listSessions
  });

  const selectedSessionId = activeSessionId ?? sessionsQuery.data?.[0]?.id ?? mockSession.id;
  const sessionQuery = useQuery({
    queryKey: ["session", selectedSessionId],
    queryFn: () => getSession(selectedSessionId),
    enabled: activeTab !== "dashboard"
  });

  const session = useMemo(
    () => sessionQuery.data ?? sessionsQuery.data?.find((item) => item.id === selectedSessionId) ?? mockSession,
    [selectedSessionId, sessionQuery.data, sessionsQuery.data]
  );

  return (
    <AppLayout
      activeTab={activeTab}
      onTabChange={setActiveTab}
      sessionName={session.name}
      status={session.status}
    >
      {activeTab === "dashboard" ? (
        <Dashboard
          sessions={sessionsQuery.data ?? [mockSession]}
          onOpenAnalysis={(sessionId) => {
            setActiveSessionId(sessionId);
            setActiveTab("analysis");
          }}
          onSessionCreated={(session) => {
            queryClient.setQueryData(["session", session.id], session);
            void queryClient.invalidateQueries({ queryKey: ["sessions"] });
            setActiveSessionId(session.id);
            setActiveTab("analysis");
          }}
        />
      ) : activeTab === "settings" ? (
        <SettingsView />
      ) : (
        <SessionDetailView session={session} />
      )}
    </AppLayout>
  );
}
