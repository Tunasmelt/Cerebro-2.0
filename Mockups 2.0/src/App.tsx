import { useState } from "react";
import Landing from "./components/Landing";
import SignIn from "./components/SignIn";
import AppShell from "./components/AppShell";

type Page = "landing" | "signin" | "app";

export default function App() {
  const [page, setPage] = useState<Page>("landing");

  if (page === "signin") {
    return (
      <SignIn
        onSignIn={() => setPage("app")}
        onBack={() => setPage("landing")}
      />
    );
  }

  if (page === "app") {
    return <AppShell />;
  }

  return (
    <Landing
      onSignIn={() => setPage("signin")}
      onTryIt={() => setPage("app")}
    />
  );
}
