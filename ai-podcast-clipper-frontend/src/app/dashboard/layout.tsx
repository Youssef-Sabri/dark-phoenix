"use server";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import NavHeader from "~/components/nav-header";
import { Toaster } from "~/components/ui/sonner";
import { auth } from "~/server/auth";
import { db } from "~/server/db";

export default async function DashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await auth();

  if (!session?.user?.id) {
    redirect("/login");
  }

  // Session is valid but the user row may be missing (e.g. account deleted
  // while a JWT session cookie was still issued). Treat it like a signed-out
  // visitor instead of crashing the dashboard with a Prisma P2025.
  const user = await db.user.findUnique({
    where: { id: session.user.id },
    select: { credits: true, email: true },
  });

  if (!user) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <NavHeader credits={user.credits} email={user.email} />
      <main className="container mx-auto flex-1 py-6">{children}</main>
      <Toaster />
    </div>
  );
}
