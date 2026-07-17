import { cleanup } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";

import { server } from "@/test/server";

server.listen({ onUnhandledRequest: "error" });
afterEach(() => { cleanup(); server.resetHandlers(); });
afterAll(() => server.close());

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", { value: ResizeObserverStub, configurable: true });
Object.defineProperty(window, "matchMedia", { value: (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }), configurable: true });
Object.defineProperty(Element.prototype, "hasPointerCapture", { value: () => false, configurable: true });
Object.defineProperty(Element.prototype, "setPointerCapture", { value: () => undefined, configurable: true });
Object.defineProperty(Element.prototype, "releasePointerCapture", { value: () => undefined, configurable: true });
Object.defineProperty(Element.prototype, "scrollIntoView", { value: () => undefined, configurable: true });
if (!("randomUUID" in window.crypto)) Object.defineProperty(window.crypto, "randomUUID", { value: () => "00000000-0000-4000-8000-000000000001", configurable: true });
