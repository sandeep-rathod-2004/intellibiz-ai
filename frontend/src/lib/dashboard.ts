import {useOutletContext} from "react-router-dom";
import type {ChangeEvent, Dispatch, SetStateAction} from "react";
import type {Dataset, DatasetAnalysis, UserProfile} from "../types";

export type ToastKind = "success" | "error" | "info";

export interface DashboardOutletContext {
  user: UserProfile;
  datasets: Dataset[];
  datasetsLoading: boolean;
  datasetsError: string;
  selectedDataset: Dataset | null;
  selectedDatasetId: number | null;
  setSelectedDatasetId: Dispatch<SetStateAction<number | null>>;
  analysis: DatasetAnalysis | null;
  analysisLoading: boolean;
  analysisError: string;
  retryAnalysis: () => void;
  refreshDatasets: () => Promise<void>;
  handleUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  downloadSample: () => Promise<void>;
  notify: (message: string, kind?: ToastKind) => void;
  theme: "dark" | "light";
  setTheme: Dispatch<SetStateAction<"dark" | "light">>;
}

export function useDashboard() {
  return useOutletContext<DashboardOutletContext>();
}
