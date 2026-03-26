using UnityEngine;

/// <summary>
/// WeaponBase - 武器基类
/// 定义所有武器的通用属性和方法
/// </summary>
public class WeaponBase : MonoBehaviour
{
    [Header("武器基础属性")]
    [SerializeField] protected string weaponName;
    [SerializeField] protected float damage = 25f;
    [SerializeField] protected float fireRate = 10f; // 每秒射击次数
    [SerializeField] protected float reloadTime = 2.5f;
    [SerializeField] protected int magazineSize = 30;
    [SerializeField] protected int reserveAmmo = 90;
    
    [Header("后坐力设置")]
    [SerializeField] protected Vector3 recoilPattern; // 后坐力模式 (上，右，左)
    [SerializeField] protected float recoilRecoveryTime = 0.2f;
    
    [Header("音效")]
    [SerializeField] protected AudioClip fireSound;
    [SerializeField] protected AudioClip reloadSound;
    [SerializeField] protected AudioClip emptySound;
    
    // 武器状态
    protected int currentMagazineAmmo;
    protected bool isReloading;
    protected bool isFiring;
    protected float lastFireTime;
    protected float currentRecoilX = 0;
    protected float currentRecoilY = 0;
    
    // 引用
    protected Transform weaponTransform;
    protected Transform muzzleFlashPoint;
    
    private void Start()
    {
        weaponTransform = transform;
        currentMagazineAmmo = magazineSize;
        isReloading = false;
        isFiring = false;
        lastFireTime = 0f;
    }
    
    /// <summary>
    /// 射击
    /// </summary>
    public virtual void Fire()
    {
        if (isReloading) return;
        
        float timeSinceLastFire = Time.time - lastFireTime;
        if (timeSinceLastFire < 1f / fireRate) return;
        
        if (currentMagazineAmmo <= 0)
        {
            PlaySound(emptySound);
            return;
        }
        
        lastFireTime = Time.time;
        currentMagazineAmmo--;
        isFiring = true;
        
        ApplyRecoil();
        PlaySound(fireSound);
        
        // 触发射线检测
        RaycastFire();
        
        if (currentMagazineAmmo == 0)
        {
            isFiring = false;
        }
    }
    
    /// <summary>
    /// 应用后坐力
    /// </summary>
    protected virtual void ApplyRecoil()
    {
        // 默认后坐力模式：向上
        currentRecoilY += recoilPattern.y;
        currentRecoilX += recoilPattern.x;
    }
    
    /// <summary>
    /// 射线射击检测
    /// </summary>
    protected void RaycastFire()
    {
        Ray ray = new Ray(weaponTransform.position, weaponTransform.forward);
        
        if (Physics.Raycast(ray, out RaycastHit hit, 100f))
        {
            Debug.Log($"击中：{hit.collider.name}");
            
            // 如果有 PlayerHealth 组件，造成伤害
            PlayerHealth targetHealth = hit.collider.GetComponent<PlayerHealth>();
            if (targetHealth != null)
            {
                targetHealth.TakeDamage((int)damage);
            }
            
            // 添加击中效果
            CreateHitEffect(hit.point);
        }
    }
    
    /// <summary>
    /// 创建击中效果
    /// </summary>
    protected void CreateHitEffect(Vector3 hitPoint)
    {
        // TODO: 创建击中粒子效果或血溅效果
    }
    
    /// <summary>
    /// 开始重新装填
    /// </summary>
    public virtual void Reload()
    {
        if (isReloading || currentMagazineAmmo == magazineSize || reserveAmmo <= 0)
        {
            return;
        }
        
        isReloading = true;
        PlaySound(reloadSound);
        
        StartCoroutine(ReloadCoroutine());
    }
    
    /// <summary>
    /// 重新装填协程
    /// </summary>
    protected System.Collections.IEnumerator ReloadCoroutine()
    {
        yield return new WaitForSeconds(reloadTime);
        
        int ammoNeeded = magazineSize - currentMagazineAmmo;
        int ammoToLoad = Mathf.Min(ammoNeeded, reserveAmmo);
        
        currentMagazineAmmo += ammoToLoad;
        reserveAmmo -= ammoToLoad;
        
        isReloading = false;
        Debug.Log($"重新装填完成：{currentMagazineAmmo}/{magazineSize}");
    }
    
    /// <summary>
    /// 播放音效
    /// </summary>
    protected void PlaySound(AudioClip clip)
    {
        if (clip != null)
        {
            AudioSource.PlayClipAtPoint(clip, weaponTransform.position);
        }
    }
    
    /// <summary>
    /// 添加备用弹药
    /// </summary>
    public void AddReserveAmmo(int amount)
    {
        reserveAmmo += amount;
    }
    
    /// <summary>
    /// 获取武器名称
    /// </summary>
    public string GetWeaponName()
    {
        return weaponName;
    }
    
    /// <summary>
    /// 获取当前弹药
    /// </summary>
    public int GetCurrentAmmo()
    {
        return currentMagazineAmmo;
    }
    
    /// <summary>
    /// 获取备用弹药
    /// </summary>
    public int GetReserveAmmo()
    {
        return reserveAmmo;
    }
    
    /// <summary>
    /// 获取是否正在装填
    /// </summary>
    public bool IsReloading()
    {
        return isReloading;
    }
}
