import type { ReactNode } from "react";

import { UploadPickerCacheBridge } from "./UploadPickerCacheBridge";

export default function EduPlus2FrontingDemoLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <>
      <UploadPickerCacheBridge />
      {children}
    </>
  );
}
