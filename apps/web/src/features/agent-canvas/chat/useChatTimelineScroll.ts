import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type UIEventHandler,
} from "react";

const BOTTOM_THRESHOLD_PX = 24;

function maxScrollTop(element: HTMLElement) {
  return Math.max(0, element.scrollHeight - element.clientHeight);
}

function isNearTimelineBottom(element: HTMLElement) {
  return maxScrollTop(element) - element.scrollTop <= BOTTOM_THRESHOLD_PX;
}

function scrollTimelineToLatest(element: HTMLElement) {
  element.scrollTop = maxScrollTop(element);
}

export function useChatTimelineScroll({
  contentVersion,
  resetKey,
}: {
  contentVersion: string;
  resetKey: string;
}) {
  const timelineRef = useRef<HTMLDivElement>(null);
  const timelineContentRef = useRef<HTMLDivElement>(null);
  const followingLatestRef = useRef(true);
  const [hasUnseenContent, setHasUnseenContent] = useState(false);

  const followLatest = useCallback(() => {
    followingLatestRef.current = true;
    setHasUnseenContent(false);
    if (timelineRef.current) scrollTimelineToLatest(timelineRef.current);
  }, []);

  const onTimelineScroll = useCallback<UIEventHandler<HTMLDivElement>>((event) => {
    const followingLatest = isNearTimelineBottom(event.currentTarget);
    followingLatestRef.current = followingLatest;
    if (followingLatest) setHasUnseenContent(false);
  }, []);

  useLayoutEffect(() => {
    followingLatestRef.current = true;
    setHasUnseenContent(false);
    if (timelineRef.current) scrollTimelineToLatest(timelineRef.current);
  }, [resetKey]);

  useLayoutEffect(() => {
    if (followingLatestRef.current) {
      if (timelineRef.current) scrollTimelineToLatest(timelineRef.current);
      return;
    }
    setHasUnseenContent(true);
  }, [contentVersion]);

  useLayoutEffect(() => {
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      if (followingLatestRef.current && timelineRef.current) {
        scrollTimelineToLatest(timelineRef.current);
      }
    });
    if (timelineRef.current) observer.observe(timelineRef.current);
    if (timelineContentRef.current) observer.observe(timelineContentRef.current);
    return () => observer.disconnect();
  }, [resetKey]);

  return {
    timelineRef,
    timelineContentRef,
    onTimelineScroll,
    hasUnseenContent,
    followLatest,
  };
}
