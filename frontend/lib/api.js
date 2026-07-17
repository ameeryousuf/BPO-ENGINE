const BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL;

export async function fetchProcess(processId, goal, episodes, redesign) {
    const params = new URLSearchParams({
        goal,
        episodes: String(episodes),
        redesign: String(redesign),
    });

    const res = await fetch(`${BASE_URL}/process/${processId}?${params.toString()}`, {
        method: "POST",
    });

    if (!res.ok) {
        throw new Error(`Request failed with status ${res.status}`);
    }

    return res.json();
}