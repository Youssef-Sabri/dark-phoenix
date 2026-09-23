"use server";

import { redirect } from "next/navigation";
import { LoginForm } from "~/components/login-form";
import { auth } from "~/server/auth";
import { db } from "~/server/db";

export default async function Page() {
  const session = await auth();

  // Only bounce to the dashboard when the session's user row actually exists.
  // A stale cookie (user deleted, e.g. the pre-cleanup owner account) must fall
  // through to the login form instead of looping dashboard <-> login.
  if (session?.user?.id) {
    const existingUser = await db.user.findUnique({
      where: { id: session.user.id },
      select: { id: true },
    });

    if (existingUser) {
      redirect("/dashboard");
    }
  }

  return (
    <div className="flex min-h-svh w-full items-center justify-center p-6 md:p-10">
      <div className="w-full max-w-sm">
        <LoginForm />
      </div>
    </div>
  );
}
