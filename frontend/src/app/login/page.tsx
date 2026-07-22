"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: () => {
      const from = searchParams.get("from");
      router.replace(from && from !== "/login" ? from : "/");
      router.refresh();
    },
  });

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6 py-12">
      <div className="space-y-6 rounded-lg border bg-card p-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">InspirationOS</h1>
          <p className="text-sm text-muted-foreground">Sign in to continue.</p>
        </div>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit.mutate();
          }}
        >
          <label className="block text-sm">
            Email
            <Input
              className="mt-1"
              type="email"
              autoComplete="username"
              data-testid="login-email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label className="block text-sm">
            Password
            <Input
              className="mt-1"
              type="password"
              autoComplete="current-password"
              data-testid="login-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          <Button
            type="submit"
            className="w-full"
            data-testid="login-submit"
            disabled={submit.isPending}
          >
            {submit.isPending ? "Signing in…" : "Sign in"}
          </Button>
          {submit.isError && (
            <p className="text-sm text-destructive" data-testid="login-error">
              {submit.error instanceof ApiError
                ? submit.error.message
                : "Sign-in failed. Try again."}
            </p>
          )}
        </form>
      </div>
    </main>
  );
}
