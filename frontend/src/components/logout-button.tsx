"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { logout } from "@/lib/api";

export function LogoutButton() {
  const router = useRouter();

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      router.replace("/login");
      router.refresh();
    },
  });

  return (
    <Button
      size="sm"
      variant="ghost"
      data-testid="logout-button"
      disabled={signOut.isPending}
      onClick={() => signOut.mutate()}
    >
      Log out
    </Button>
  );
}
