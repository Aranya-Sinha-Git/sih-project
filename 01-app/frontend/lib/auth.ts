export function normalizeUsername(username:string):string{return username.trim().toLowerCase().replace(/\s+/g,' ')}
export function usernameToInternalEmail(username:string):string{return `${normalizeUsername(username)}@users.sif-sentinel.invalid`}
