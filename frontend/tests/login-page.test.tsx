import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return { ...original, login: vi.fn() };
});

const replaceMock = vi.fn();
const refreshMock = vi.fn();
const searchParamsGetMock = vi.fn().mockReturnValue(null);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: refreshMock }),
  useSearchParams: () => ({ get: searchParamsGetMock }),
}));

const mockedLogin = vi.mocked(api.login);

function renderWithClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <LoginPage />
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockedLogin.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
    searchParamsGetMock.mockReset().mockReturnValue(null);
  });

  it("submits email and password, then redirects to /", async () => {
    mockedLogin.mockResolvedValue({ id: 1, email: "test@example.com" });
    renderWithClient();

    await userEvent.type(screen.getByTestId("login-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("login-password"), "hunter2");
    await userEvent.click(screen.getByTestId("login-submit"));

    expect(mockedLogin).toHaveBeenCalledWith("test@example.com", "hunter2");
    expect(await screen.findByTestId("login-submit")).toBeInTheDocument();
    expect(replaceMock).toHaveBeenCalledWith("/");
  });

  it("redirects back to the originating page when given a from param", async () => {
    searchParamsGetMock.mockReturnValue("/inbox");
    mockedLogin.mockResolvedValue({ id: 1, email: "test@example.com" });
    renderWithClient();

    await userEvent.type(screen.getByTestId("login-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("login-password"), "hunter2");
    await userEvent.click(screen.getByTestId("login-submit"));

    expect(replaceMock).toHaveBeenCalledWith("/inbox");
  });

  it("shows an error message on failed login and does not redirect", async () => {
    mockedLogin.mockRejectedValue(new api.ApiError(401, null, "invalid email or password"));
    renderWithClient();

    await userEvent.type(screen.getByTestId("login-email"), "test@example.com");
    await userEvent.type(screen.getByTestId("login-password"), "wrong");
    await userEvent.click(screen.getByTestId("login-submit"));

    expect(await screen.findByTestId("login-error")).toHaveTextContent(
      "invalid email or password",
    );
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
