using UnityEngine;

/// <summary>
/// 声音管理系统 - 统一管理游戏音效和背景音乐
/// </summary>
public class SoundManager : MonoBehaviour
{
    public static SoundManager Instance;
    
    [Header("音效资源")]
    [Tooltip("射击音效")]
    public AudioClip shootSound;
    
    [Tooltip("换弹音效")]
    public AudioClip reloadSound;
    
    [Tooltip("脚步声")]
    public AudioClip footstepsSound;
    
    [Tooltip("爆炸音效")]
    public AudioClip explosionSound;
    
    [Tooltip("炸弹放置音效")]
    public AudioClip bombPlaceSound;
    
    [Tooltip("炸弹倒计时音效")]
    public AudioClip bombCountdownSound;
    
    [Tooltip("回合开始音效")]
    public AudioClip roundStartSound;
    
    [Header("音量设置")]
    [Tooltip("主音量")]
    [Range(0f, 1f)]
    public float masterVolume = 1f;
    
    [Tooltip("音效音量")]
    [Range(0f, 1f)]
    public float sfxVolume = 0.8f;
    
    [Tooltip("背景音乐音量")]
    [Range(0f, 1f)]
    public float bgmVolume = 0.5f;
    
    private AudioSource sfxSource;
    private AudioSource bgmSource;
    
    private void Awake()
    {
        // 单例模式
        if (Instance == null)
        {
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }
        else
        {
            Destroy(gameObject);
            return;
        }
        
        // 初始化音效源
        sfxSource = GetComponent<AudioSource>();
        if (sfxSource == null)
        {
            sfxSource = gameObject.AddComponent<AudioSource>();
            sfxSource.playOnAwake = false;
            sfxSource.spatialBlend = 0f; // 2D 音效
        }
        
        // 初始化背景音乐源
        bgmSource = gameObject.AddComponent<AudioSource>();
        bgmSource.playOnAwake = true;
        bgmSource.loop = true;
        bgmSource.spatialBlend = 0f;
    }
    
    private void Start()
    {
        SetMasterVolume(masterVolume);
    }
    
    /// <summary>
    /// 播放音效
    /// </summary>
    public void PlaySFX(AudioClip clip, float volumeOverride = -1f)
    {
        if (sfxSource != null && clip != null)
        {
            float volume = (volumeOverride > 0f) ? volumeOverride : sfxVolume;
            sfxSource.PlayOneShot(clip, volume);
        }
    }
    
    /// <summary>
    /// 播放射击音效
    /// </summary>
    public void PlayShootSound()
    {
        PlaySFX(shootSound);
    }
    
    /// <summary>
    /// 播放换弹音效
    /// </summary>
    public void PlayReloadSound()
    {
        PlaySFX(reloadSound);
    }
    
    /// <summary>
    /// 播放脚步声
    /// </summary>
    public void PlayFootstepsSound()
    {
        PlaySFX(footstepsSound);
    }
    
    /// <summary>
    /// 播放爆炸音效
    /// </summary>
    public void PlayExplosionSound()
    {
        PlaySFX(explosionSound);
    }
    
    /// <summary>
    /// 播放炸弹放置音效
    /// </summary>
    public void PlayBombPlaceSound()
    {
        PlaySFX(bombPlaceSound);
    }
    
    /// <summary>
    /// 播放炸弹倒计时音效
    /// </summary>
    public void PlayBombCountdownSound()
    {
        PlaySFX(bombCountdownSound);
    }
    
    /// <summary>
    /// 播放回合开始音效
    /// </summary>
    public void PlayRoundStartSound()
    {
        PlaySFX(roundStartSound);
    }
    
    /// <summary>
    /// 设置主音量
    /// </summary>
    public void SetMasterVolume(float volume)
    {
        masterVolume = volume;
        if (sfxSource != null)
        {
            sfxSource.volume = sfxVolume * masterVolume;
        }
        if (bgmSource != null)
        {
            bgmSource.volume = bgmVolume * masterVolume;
        }
    }
    
    /// <summary>
    /// 设置音效音量
    /// </summary>
    public void SetSFXVolume(float volume)
    {
        sfxVolume = volume;
        if (sfxSource != null)
        {
            sfxSource.volume = sfxVolume * masterVolume;
        }
    }
    
    /// <summary>
    /// 设置背景音乐
    /// </summary>
    public void SetBackgroundMusic(AudioClip clip)
    {
        if (bgmSource != null && clip != null)
        {
            bgmSource.clip = clip;
            bgmSource.Play();
        }
    }
    
    /// <summary>
    /// 停止背景音乐
    /// </summary>
    public void StopBackgroundMusic()
    {
        if (bgmSource != null)
        {
            bgmSource.Stop();
        }
    }
}
