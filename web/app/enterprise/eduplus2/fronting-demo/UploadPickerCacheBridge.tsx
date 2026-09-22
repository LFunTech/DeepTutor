"use client";

import { useEffect } from "react";

import { installEduPlus2ResourceUploadPickerBridge } from "@/lib/eduplus2-fronting-demo-upload-picker-bridge";

export function UploadPickerCacheBridge() {
  useEffect(() => installEduPlus2ResourceUploadPickerBridge(), []);

  return null;
}
