import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageResolutionCapabilitiesV1 } from "../../../api/providerRegistry.ts";
import { ImageResolutionControls } from "./ImageResolutionControls.tsx";
import {
  imageResolutionIssues,
  staleImageResolutionParameters,
} from "./imageResolutionCapabilities.ts";

const sizeCapabilities: ImageResolutionCapabilitiesV1 = {
  parameter_modes: ["size"],
  size_options: ["2048x2048", "2560x1440", "1440x2560", "2304x1728", "1728x2304"],
  resolution_options: [],
  aspect_ratio_options: [],
  sizes_by_aspect_ratio: {
    "1:1": "2048x2048",
    "16:9": "2560x1440",
    "9:16": "1440x2560",
    "4:3": "2304x1728",
    "3:4": "1728x2304",
  },
  pixel_bounds: { minimum: 512, maximum: 4096 },
  default_parameters: {},
};

const pairCapabilities: ImageResolutionCapabilitiesV1 = {
  parameter_modes: ["resolution_with_aspect_ratio"],
  size_options: [],
  resolution_options: ["1K", "2K", "4K"],
  aspect_ratio_options: ["1:1", "16:9", "9:16", "4:3", "3:4"],
  sizes_by_aspect_ratio: {},
  pixel_bounds: null,
  default_parameters: {},
};

afterEach(() => cleanup());

describe("ImageResolutionControls", () => {
  it("submits only the size parameter in size mode", () => {
    const onChange = vi.fn();
    render(
      <ImageResolutionControls
        capabilities={sizeCapabilities}
        parameters={{ resolution: "2K", aspect_ratio: "16:9" }}
        disabled={false}
        onChange={onChange}
      />,
    );
    const select = screen.getByLabelText("Size") as HTMLSelectElement;
    expect(select.value).toBe("");
    fireEvent.change(select, { target: { value: "2560x1440" } });
    expect(onChange).toHaveBeenLastCalledWith({ size: "2560x1440" });
  });

  it("keeps resolution and aspect ratio paired and drops size in pair mode", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ImageResolutionControls
        capabilities={pairCapabilities}
        parameters={{ size: "2048x2048" }}
        disabled={false}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Resolution"), { target: { value: "2K" } });
    expect(onChange).toHaveBeenLastCalledWith({ resolution: "2K", aspect_ratio: "1:1" });

    rerender(
      <ImageResolutionControls
        capabilities={pairCapabilities}
        parameters={{ resolution: "2K", aspect_ratio: "1:1" }}
        disabled={false}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Ratio"), { target: { value: "16:9" } });
    expect(onChange).toHaveBeenLastCalledWith({ resolution: "2K", aspect_ratio: "16:9" });
  });

  it("shows default parameters as the initial selection without writing them", () => {
    const onChange = vi.fn();
    render(
      <ImageResolutionControls
        capabilities={{ ...pairCapabilities, default_parameters: { resolution: "2K", aspect_ratio: "16:9" } }}
        parameters={{}}
        disabled={false}
        onChange={onChange}
      />,
    );
    expect((screen.getByLabelText("Resolution") as HTMLSelectElement).value).toBe("2K");
    expect((screen.getByLabelText("Ratio") as HTMLSelectElement).value).toBe("16:9");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reports a half-filled pair and preserves unsupported values", () => {
    expect(imageResolutionIssues(pairCapabilities, { resolution: "2K" })).toEqual([{
      name: "aspect_ratio",
      message: "Choose an aspect ratio to send with the resolution.",
    }]);
    expect(imageResolutionIssues(pairCapabilities, {})).toEqual([]);
    expect(imageResolutionIssues(sizeCapabilities, { size: "1024x1024" })).toEqual([]);

    render(
      <ImageResolutionControls
        capabilities={pairCapabilities}
        parameters={{ resolution: "8K" }}
        disabled={false}
        onChange={vi.fn()}
      />,
    );
    expect((screen.getByLabelText("Resolution") as HTMLSelectElement).value).toBe("8K");
    expect(screen.getByText("8K (unsupported)")).toBeTruthy();
    expect(screen.getByText("Choose an aspect ratio to send with the resolution.")).toBeTruthy();
  });

  it("drops parameters a model does not declare for its resolution mode", () => {
    expect(staleImageResolutionParameters(sizeCapabilities, {
      size: "2560x1440",
      quality: "high",
      resolution: "2K",
      aspect_ratio: "16:9",
    })).toEqual(["resolution", "aspect_ratio"]);
    expect(staleImageResolutionParameters(pairCapabilities, {
      size: "2048x2048",
      quality: "high",
    })).toEqual(["size"]);
    expect(staleImageResolutionParameters(sizeCapabilities, { quality: "high" })).toEqual([]);
  });
});
